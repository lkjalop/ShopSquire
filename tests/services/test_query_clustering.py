from src.app.services.nlp_query_clustering import QueryClusterer


def test_query_clustering_basic():
    queries = [
        "Where is my order?",
        "Order status update",
        "Track shipment",
        "Refund policy details",
        "How to return an item",
        "Return window length",
        "Shipping delay issues",
        "Late delivery help",
    ]
    clusters = QueryClusterer().cluster(queries, min_cluster_size=2)
    assert clusters, "Should produce at least one cluster"
    total = sum(c.size for c in clusters)
    assert total == len(queries)
