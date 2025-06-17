from flask import Flask, jsonify
from google.cloud import bigquery
from dotenv import load_dotenv
import os
import openai
print(f"✅ openai version: {openai.__version__}")
from openai import OpenAI

app = Flask(__name__)

print("✅ Flask app initialized")

load_dotenv()  # .env ファイルを読み込み、環境変数に反映
print("✅ .env loaded")

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    print("❌ OPENAI_API_KEY is not set")
else:
    print(f"✅ OPENAI_API_KEY loaded: {api_key[:5]}***")

@app.route("/")
def index():
    try:
        print("🔄 Initializing OpenAI client...")
        openai_client = OpenAI(api_key=api_key)
        print("✅ OpenAI client initialized")

        bigquery_client = bigquery.Client()
        query = """
            SELECT * 
            FROM `sic-ouraring-verify.gcube.sleep` 
            WHERE summary_date BETWEEN '2020-09-01' AND '2020-09-30' 
            ORDER BY summary_date ASC 
            LIMIT 3
        """
        query_job = bigquery_client.query(query)
        results = query_job.result()
        data_list = [dict(row.items()) for row in results]

        prompt_data = "\n".join([str(row) for row in data_list])
        print(f"📋 Prompt data prepared: {prompt_data}")

        # OpenAI GPT-4o にリクエスト
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは専門的な医療知識を持つ医師です。"},
                {"role": "user", "content": f"以下のOuraRingから取得した健康データから医学的アドバイスをください：\n\n{prompt_data}"}
            ]
        )

        llm_advice_content = response.choices[0].message.content
        print(f"💬 GPT response: {llm_advice_content}")

        # BigQueryに保存
        table_id = "llm_advicebot.llm_advice_makino"
        rows_to_insert = [{"llm_advice": llm_advice_content}]
        errors = bigquery_client.insert_rows_json(table_id, rows_to_insert)
        if errors:
            print(f"❌ Failed to insert rows: {errors}")
            return jsonify({"error": "BigQuery insert failed", "details": errors}), 500

        print("✅ GPT response saved to BigQuery")

        # GPTの応答を返却
        return llm_advice_content
    except Exception as e:
        print(f"❌ Exception occurred: {e}")
        return jsonify({"error": str(e)}), 500