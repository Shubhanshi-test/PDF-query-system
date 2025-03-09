# ==================================================================================
# PDF Query System with ColPali + GraphDB + ML-Based Retrieval
# ==================================================================================
# This script processes tabular data from PDFs, stores it in DuckDB & GraphDB, and
# uses ML-based Semantic Search when exact SQL lookups fail.
# ==================================================================================

import pdfplumber
import pandas as pd
import duckdb
from neo4j import GraphDatabase
from transformers import pipeline
from sentence_transformers import SentenceTransformer, util
import colpali

# ==================================================================================
# Load ML Models
# ==================================================================================
# Named Entity Recognition (NER) for extracting material names from queries
ner_pipeline = pipeline("ner", model="dbmdz/bert-large-cased-finetuned-conll03-english")

# Semantic Model for fuzzy matching when SQL lookup fails
semantic_model = SentenceTransformer("all-MiniLM-L6-v2")

# ==================================================================================
# Step 1: Extract Tables using ColPali (Optimized Table Extraction)
# ==================================================================================
def extract_tables(pdf_path):
    """Extract tables using ColPali for structured parsing."""
    tables = colpali.extract_tables(pdf_path, method="auto")  # Automatically detects table structure
    return [pd.DataFrame(table) for table in tables]

# ==================================================================================
# Step 2: Store Data in DuckDB (for Structured Queries)
# ==================================================================================
def store_in_duckdb(tables):
    """Store extracted tables in DuckDB for fast SQL lookups."""
    con = duckdb.connect(":memory:")
    table_references = []

    for i, table in enumerate(tables):
        table.columns = [f"col_{j}" for j in range(len(table.columns))]
        table_name = f"table_{i}"
        con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM table", {"table": table})
        table_references.append(table_name)

    return con, table_references

# ==================================================================================
# Step 3: Store Data in GraphDB (for Relationship Queries)
# ==================================================================================
class GraphDB:
    """Handles GraphDB interactions for material relationships."""
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def add_material(self, name, qualification):
        """Store material and its qualification in GraphDB."""
        with self.driver.session() as session:
            session.run("CREATE (m:Material {name: $name, qualification: $qualification})",
                        name=name, qualification=qualification)

    def query_material(self, name):
        """Retrieve qualification of a material from GraphDB."""
        with self.driver.session() as session:
            result = session.run("MATCH (m:Material {name: $name}) RETURN m.qualification", name=name)
            return result.single()[0] if result.single() else None

# ==================================================================================
# Step 4: Query Understanding (NER for Extracting Material Names)
# ==================================================================================
def extract_query_entities(query):
    """Extract key entities (like material names) using NER."""
    entities = ner_pipeline(query)
    return [ent["word"] for ent in entities if ent["entity"] in ["B-MISC", "I-MISC", "B-ORG", "I-ORG"]]

# ==================================================================================
# Step 5: Query Execution (GraphDB → SQL → Semantic Search)
# ==================================================================================
def query_system(query, db_con, graph_db, tables):
    """Process query using GraphDB, SQL, and Semantic Search as fallback."""

    # Step 5.1: Extract material name from query
    entities = extract_query_entities(query)
    material_name = " ".join(entities) if entities else None

    # Step 5.2: Check GraphDB first
    qualification = graph_db.query_material(material_name) if material_name else None
    if qualification:
        return f"The qualification of {material_name} is {qualification}."

    # Step 5.3: SQL Lookup in DuckDB
    sql_query = f"SELECT * FROM table_0 WHERE col_0 = '{material_name}'"
    result = db_con.execute(sql_query).fetchall()
    if result:
        return result[0][1]  # Returning qualification from structured data

    # Step 5.4: If SQL fails, use Semantic Search
    query_embedding = semantic_model.encode(query, convert_to_tensor=True)
    table_texts = [" ".join(map(str, row)) for table in tables for _, row in table.iterrows()]
    table_embeddings = semantic_model.encode(table_texts, convert_to_tensor=True)
    
    similarity_scores = util.pytorch_cos_sim(query_embedding, table_embeddings)
    best_match_idx = similarity_scores.argmax().item()
    best_match_text = table_texts[best_match_idx]

    return f"Closest match: {best_match_text}"

# ==================================================================================
# Example Usage
# ==================================================================================
pdf_path = "materials.pdf"

# Step 1: Extract tables using ColPali
tables = extract_tables(pdf_path)

# Step 2: Store in DuckDB
db_con, table_references = store_in_duckdb(tables)

# Step 3: Initialize GraphDB and store sample data
graph_db = GraphDB("bolt://localhost:7687", "neo4j", "password")
graph_db.add_material("Titanium Alloy", "Grade 5")

# Step 4: Query the system
query = "What is the qualification of Titanium Alloy?"
answer = query_system(query, db_con, graph_db, tables)
print(answer)  # Returns the best match from SQL or Semantic Search
