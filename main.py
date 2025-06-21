from flask import Flask, jsonify
from google.cloud import bigquery
from dotenv import load_dotenv
import os
import openai
print(f"✅ openai version: {openai.__version__}")
from openai import OpenAI
import json
from datetime import date
from collections import defaultdict
import time
import httpx

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
WITH sleep AS (
  SELECT 
    summary_date,
    participant_uid,
    score,
    total,
    light,
    rem,
    deep
  FROM `sic-ouraring-verify.gcube.sleep`
  WHERE total >= 3600
),
activity AS (
  SELECT 
    summary_date,
    participant_uid,
    non_wear,
    inactive,
    inactivity_alerts,
    steps
  FROM `sic-ouraring-verify.gcube.activity`
  WHERE non_wear <= 14400
)

SELECT 
  s.summary_date AS date,
  s.participant_uid AS id,
  s.score AS sleep_score,
  s.total AS total_sleep_seconds,
  s.light AS light_sleep_seconds,
  s.rem AS rem_sleep_seconds,
  s.deep AS deep_sleep_seconds,
  a.steps
FROM sleep s
LEFT JOIN activity a
  ON s.summary_date = a.summary_date AND s.participant_uid = a.participant_uid
WHERE s.summary_date BETWEEN DATE_TRUNC(CURRENT_DATE(), MONTH) AND LAST_DAY(CURRENT_DATE())
ORDER BY s.participant_uid ASC,s.summary_date ASC
LIMIT 10
        """
        query_job = bigquery_client.query(query)
        results = query_job.result()
        data_list = [dict(row.items()) for row in results]

        # Group data by participant ID
        data_by_id = defaultdict(list)
        for row in data_list:
            row_copy = dict(row)
            if 'date' in row_copy and isinstance(row_copy['date'], date):
                row_copy['date'] = row_copy['date'].isoformat()
            data_by_id[row['id']].append(row_copy)

        all_rows_to_insert = []
        all_llm_responses = []

        # Process each participant's data
        for participant_id, user_data in data_by_id.items():
            prompt_data = "\n".join([str(item) for item in user_data])
            print(f"📋 Prompt data prepared for participant {participant_id}")

            # OpenAI GPT-4o にリクエスト（リトライ機能付き）
            max_retries = 3
            retry_delay = 2  # 秒
            
            for attempt in range(max_retries):
                try:
                    response = openai_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": """あなたは専門的な医療知識を持つ医師です。
以下の形式のJSONで回答してください：
{
    "sleep_analysis": "睡眠に関する分析とアドバイス",
    "activity_analysis": "活動量に関する分析とアドバイス",
    "readiness_analysis": "体調に関する分析とアドバイス",
    "recommendations": "具体的な改善提案",
    "overall_assessment": "総合的な評価"
}
                 
最終応答は、"{"で始まり"}"で終わる。または"["で始まり"]"で終わるJSONのみを出力し、JSON以外の文字は一切応答に含めないでください。"""},
                            {"role": "user", "content": f"以下のOuraRingから取得した健康データから医学的アドバイスをください：\n\n{prompt_data}"}
                        ],
                        timeout=60  # 60秒のタイムアウト
                    )
                    
                    llm_advice_content = response.choices[0].message.content
                    print(f"💬 GPT response for {participant_id}: {llm_advice_content}")
                    break  # 成功したらループを抜ける
                    
                except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
                    print(f"⚠️ Network error for {participant_id} (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2  # 指数バックオフ
                        continue
                    else:
                        print(f"❌ Failed to get response for {participant_id} after {max_retries} attempts")
                        continue
                except Exception as e:
                    print(f"❌ Unexpected error for {participant_id}: {e}")
                    continue

            # マークダウンのコードブロック記法を除去
            llm_advice_content = llm_advice_content.replace("```json", "").replace("```", "").strip()

            # JSON文字列をPythonオブジェクトに変換
            try:
                advice_data = json.loads(llm_advice_content)
                all_llm_responses.append({participant_id: advice_data})
            except json.JSONDecodeError as e:
                print(f"❌ Failed to parse JSON response for {participant_id}: {e}")
                continue # Skip this participant if JSON is invalid

            # BigQueryに保存する行を準備
            rows_to_insert = {
                "summary_date": date.today().isoformat(),
                "participant_uid": participant_id,
                "sleep_analysis": advice_data.get("sleep_analysis", ""),
                "activity_analysis": advice_data.get("activity_analysis", ""),
                "readiness_analysis": advice_data.get("readiness_analysis", ""),
                "recommendations": advice_data.get("recommendations", ""),
                "overall_assessment": advice_data.get("overall_assessment", "")
            }
            all_rows_to_insert.append(rows_to_insert)
            
            # 各リクエスト間に少し待機時間を入れる
            time.sleep(1)

        # BigQueryに一括で保存
        if all_rows_to_insert:
            table_id = "llm_advicebot.llm_advice_makino"
            errors = bigquery_client.insert_rows_json(table_id, all_rows_to_insert)
            if errors:
                print(f"❌ Failed to insert rows: {errors}")
                return jsonify({"error": "BigQuery insert failed", "details": errors}), 500
            print(f"✅ {len(all_rows_to_insert)} records saved to BigQuery")
        else:
            print("✅ No new records to save.")

        # GPTの応答を返却
        return jsonify(all_llm_responses)
    except Exception as e:
        print(f"❌ Exception occurred: {e}")
        return jsonify({"error": str(e)}), 500