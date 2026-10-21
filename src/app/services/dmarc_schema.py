"""Portable DMARC storage; report ownership scopes every child record."""
from sqlalchemy import MetaData, Table, Column, Integer, BigInteger, Text, ForeignKey

metadata = MetaData()
reports = Table('dmarc_reports', metadata,
    Column('id', Integer, primary_key=True), Column('tenant_id', Text, nullable=True),
    Column('org_name', Text), Column('domain', Text),
    Column('begin', BigInteger), Column('end', BigInteger), Column('report_id', Text))
records = Table('dmarc_records', metadata,
    Column('id', Integer, primary_key=True),
    Column('report_fk', Integer, ForeignKey('dmarc_reports.id')),
    Column('source_ip', Text), Column('count', Integer), Column('spf', Text),
    Column('dkim', Text), Column('disposition', Text))
