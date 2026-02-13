#!/usr/bin/env python3
"""Load `data/faq_kb.json` into a simple DB table `faq_kb` for RAG retrieval.
This creates a minimal table in the same SQLite DB and upserts entries.
"""
import os
import json
import uuid
from src.app.models.db import db_session

KB_PATH = os.path.join(os.getcwd(), "data", "faq_kb.json")


def ensure_table(sess):
    sess.execute("CREATE TABLE IF NOT EXISTS faq_kb (id TEXT PRIMARY KEY, intent TEXT, title TEXT, description TEXT, troubleshooting TEXT, evidence_requirements TEXT, auto_approve_threshold_cents INT)")


def load():
    with open(KB_PATH, "r", encoding="utf8") as f:
        kb = json.load(f)
    with db_session() as sess:
        ensure_table(sess)
        created = 0
        updated = 0
        for item in kb:
            iid = item.get("id") or str(uuid.uuid4())
            row = sess.execute("SELECT id FROM faq_kb WHERE id = :id", {"id": iid}).fetchone()
            troubleshooting = json.dumps(item.get("troubleshooting_steps", []), ensure_ascii=False)
            evidence = json.dumps(item.get("evidence_requirements", []), ensure_ascii=False)
            if row:
                sess.execute("UPDATE faq_kb SET intent=:intent, title=:title, description=:desc, troubleshooting=:tr, evidence_requirements=:ev, auto_approve_threshold_cents=:th WHERE id=:id",
                             {"intent": item.get("intent"), "title": item.get("title"), "desc": item.get("description"), "tr": troubleshooting, "ev": evidence, "th": item.get("auto_approve_threshold_cents", 0), "id": iid})
                updated += 1
            else:
                sess.execute("INSERT INTO faq_kb (id,intent,title,description,troubleshooting,evidence_requirements,auto_approve_threshold_cents) VALUES (:id,:intent,:title,:desc,:tr,:ev,:th)",
                             {"id": iid, "intent": item.get("intent"), "title": item.get("title"), "desc": item.get("description"), "tr": troubleshooting, "ev": evidence, "th": item.get("auto_approve_threshold_cents", 0)})
                created += 1
        try:
            sess.commit()
        except Exception:
            sess.rollback()
            raise
    print(f"FAQ KB loaded: created={created} updated={updated}")


if __name__ == '__main__':
    load()
