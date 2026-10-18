# graph_builder.py (Grafo de Enlaces e Indexación)
# Qué hace: Coordina a los tres anteriores. Aplica las heurísticas iniciales y los resultados de los embeddings para construir el "grafo de enlaces" definitivo entre los fragmentos de código y las secciones de la documentación.

# Responsabilidad clave: Persistir y serializar este mapeo resultante en un archivo JSON estructurado dentro del repositorio (code_to_docs_graph.json).