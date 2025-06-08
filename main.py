from flask import Flask, jsonify
from google.cloud import bigquery
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)

load_dotenv()  # .env ファイルを読み込み、環境変数に反映

api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

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
        prompt_data = "\n".join([str(row) for row in data_list])

        # OpenAI GPT-4o にリクエスト
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは専門的な医療知識を持つ医師です。"},
                {"role": "user", "content": f"以下のOuraRingから取得した健康データから医学的アドバイスをください：\n\n{prompt_data}"}
            ]
        )

        # GPTの応答を返却
        return response.choices[0].message.content
    except Exception as e:
        return jsonify({"error": str(e)}), 500