from flask import Flask, jsonify
from google.cloud import bigquery

app = Flask(__name__)

@app.route("/")
def index():
    try:
        client = bigquery.Client()
        query = """
            SELECT *
            FROM `dev.syacho_kojin_copy`
            LIMIT 10
        """
        query_job = client.query(query)
        results = query_job.result()

        data = [dict(row.items()) for row in results]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500