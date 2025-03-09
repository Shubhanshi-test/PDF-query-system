import pdfplumber  # Extract structured tables from PDFs
import pandas as pd  # Handle table data in DataFrames
import duckdb  # Fast in-memory SQL queries for structured data
from neo4j import GraphDatabase  # GraphDB to manage relationships between materials
from transformers import pipeline  # Named Entity Recognition (NER) for query understanding
from sentence_transformers import SentenceTransformer, util  # Semantic search for approximate matches

# Load NLP Models for Query Understanding
ner_pipeline = pipeline("ner", model="dbmdz/bert-large-cased-finetuned-conll03-english")  # Identify key entities
semantic_model = SentenceTransformer("all-MiniLM-L6-v2")  # Semantic similarity for fuzzy search

# Step 1: Extract Tables from PDFs
def extract_tables(pdf_path):
    """Extract tables from a PDF and return them as DataFrames."""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            extracted_tables = page.extract_tables()  # Extract tables on each page
            for table in extracted_tables:
                tables.append(pd.DataFrame(table))  # Convert each table into a DataFrame
    return tables

# Step 2: Store Data in DuckDB (for structured table querying)
def store_in_duckdb(tables):
    """Store extracted tables in DuckDB for fast SQL querying."""
    con = duckdb.connect(":memory:")  # In-memory database for speed
    for i, table in enumerate(tables):
        table.columns = [f"col_{j}" for j in range(len(table.columns))]  # Normalize column names
        con.execute(f"CREATE TABLE table_{i} AS SELECT * FROM table", {"table": table})  # Store table
    return con

# Step 3: Store Data in GraphDB (for handling relationships between entities)
class GraphDB:
    """Class to interact with a Neo4j database."""

    def __init__(self, uri, user, password):
        """Initialize GraphDB connection."""
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        """Close the database connection."""
        self.driver.close()

    def add_material(self, name, qualification):
        """Add a material and its qualification to the graph database."""
        with self.driver.session() as session:
            session.run("CREATE (m:Material {name: $name, qualification: $qualification})",
                        name=name, qualification=qualification)

    def query_material(self, name):
        """Retrieve a material's qualification from GraphDB."""
        with self.driver.session() as session:
            result = session.run("MATCH (m:Material {name: $name}) RETURN m.qualification", name=name)
            return result.single()[0] if result.single() else None

# Step 4: Query Understanding using Named Entity Recognition (NER)
def extract_query_entities(query):
    """Extract key entities (materials) from a query using NER."""
    entities = ner_pipeline(query)
    return [ent["word"] for ent in entities if ent["entity"] in ["B-MISC", "I-MISC", "B-ORG", "I-ORG"]]

# Step 5: Query Execution (GraphDB → Semantic Search → SQL)
def query_system(query, db_con, graph_db):
    """Process a user query by searching the GraphDB, semantic model, and DuckDB."""

    # Step 5.1: Extract material name using NER
    entities = extract_query_entities(query)
    material_name = " ".join(entities) if entities else None

    # Step 5.2: Try fetching data from GraphDB first (fastest)
    qualification = graph_db.query_material(material_name) if material_name else None
    if qualification:
        return f"The qualification of {material_name} is {qualification}."
    
    # Step 5.3: If GraphDB fails, use SQL search
    sql_query = f"SELECT * FROM table_0 WHERE col_0 = '{material_name}'"
    result = db_con.execute(sql_query).fetchall()

    return result[0][1] if result else "No data found."

# Example Usage
pdf_path = "materials.pdf"  # Path to the PDF file containing materials data

# Step 1: Extract tables from PDF
tables = extract_tables(pdf_path)

# Step 2: Store extracted tables in DuckDB
db_con = store_in_duckdb(tables)

# Step 3: Initialize GraphDB and store sample data
graph_db = GraphDB("bolt://localhost:7687", "neo4j", "password")
graph_db.add_material("Titanium Alloy", "Grade 5")

# Step 4: Query the system for material qualification
query = "What is the qualification of Titanium Alloy?"
answer = query_system(query, db_con, graph_db)
print(answer)  # Expected Output: "The qualification of Titanium Alloy is Grade 5."
