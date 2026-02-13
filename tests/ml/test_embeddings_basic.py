from src.app.services.embeddings import SimpleEmbeddings


def test_embeddings_similarity_ordering():
    emb = SimpleEmbeddings()
    a = emb.embed_text("BrandX Laptop 16GB RAM")
    b = emb.embed_text("BrandX Notebook 16GB")
    c = emb.embed_text("Coffee Mug Ceramic")
    sim_ab = emb.cosine(a, b)
    sim_ac = emb.cosine(a, c)
    assert sim_ab > sim_ac
