from flask import Flask, jsonify
from google.cloud import bigquery
from dotenv import load_dotenv
import os
import openai
print(f"✅ openai version: {openai.__version__}")
from openai import OpenAI
import json
from datetime import date

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
  a.steps,
FROM sleep s
LEFT JOIN activity a
  ON s.summary_date = a.summary_date AND s.participant_uid = a.participant_uid
WHERE s.summary_date BETWEEN DATE_TRUNC(CURRENT_DATE(), MONTH) AND LAST_DAY(CURRENT_DATE())
ORDER BY s.participant_uid ASC,s.summary_date ASC
LIMIT 1000
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
                {"role": "system", "content": """あなたは健康状態を管理するベテランのアドバイザーです。
データからその人の健康状態を知り、適切なアドバイスをすることがあなたの仕事です。
生体情報(時間、運動量)を持っています。
sleep_scoreは、数値が高いほど質の高い睡眠ができていることを意味します。
total_sleep_secondsは深い睡眠、light_sleep_secondsは浅い睡眠、rem_sleep_secondsはレム睡眠を表します。
stepsは1日の歩数を表します。

これから扱う生体情報には、データ更新が途中で止まっている可能性があり、
欠損値や連続した同じ値が含まれているかもしれませんが、
使える範囲でデータ分析を行い、必要以上に気にしすぎないでください。
                 
以下の形式のJSONでidごとに分けて回答してください：
{
    "id": "id",
    "sleep_analysis": "睡眠に関する分析とアドバイス",
    "activity_analysis": "歩数に関する分析とアドバイス",
    "recommendations": "具体的な改善提案",
    "overall_assessment": "総合的な評価"
}
                 
最終応答は、"{"で始まり"}"で終わる。または"["で始まり"]"で終わるJSONのみを出力し、JSON以外の文字は一切応答に含めないでください。"""},
                {"role": "user", "content": f"""今ある人の1週間分の生体情報(時間、運動量)と
1ヶ月の生体情報を持っています。

直近の1週間分と1ヶ月分の生体情報の違いがあればわかりやすく説明してください。
相手は専門家ではなく一般の人なので、数値だけに頼らず、
運動量、睡眠時間などを丁寧に比較し、
より分かりやすい文章で説明を行ってください。：\n\n{prompt_data}"""}
            ],
                timeout=300  # 最大タイムアウト値（5分）を設定
        )

        llm_advice_content = response.choices[0].message.content
        print(f"💬 GPT response: {llm_advice_content}")

        # マークダウンのコードブロック記法を除去
        llm_advice_content = llm_advice_content.replace("```json", "").replace("```", "").strip()

        # JSON文字列をPythonオブジェクトに変換
        try:
            advice_data = json.loads(llm_advice_content)
            print(f"✅ JSON parsed successfully: {type(advice_data)}")
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse JSON response: {e}")
            print(f"❌ Raw response: {llm_advice_content}")
            return jsonify({"error": "Invalid JSON response from GPT"}), 500

        # BigQueryに保存
        table_id = "llm_advicebot.llm_advice_makino"
        
        # advice_dataがリストの場合は各要素を処理、辞書の場合はリストに変換
        if isinstance(advice_data, list):
            advice_list = advice_data
        elif isinstance(advice_data, dict):
            advice_list = [advice_data]
        else:
            print(f"❌ Unexpected data structure: {type(advice_data)}")
            return jsonify({"error": "Unexpected response structure from GPT"}), 500

        # 各IDのデータをBigQueryに保存
        rows_to_insert = []
        for advice_item in advice_list:
            if isinstance(advice_item, dict) and "id" in advice_item:
                row = {
                    "summary_date": date.today().isoformat(),
                    "participant_uid": advice_item.get("id", ""),
                    "sleep_analysis": advice_item.get("sleep_analysis", ""),
                    "activity_analysis": advice_item.get("activity_analysis", ""),
                    "recommendations": advice_item.get("recommendations", ""),
                    "overall_assessment": advice_item.get("overall_assessment", "")
                }
                rows_to_insert.append(row)
                print(f"✅ Prepared data for ID: {advice_item.get('id', '')}")
            else:
                print(f"❌ Skipping invalid advice item: {advice_item}")

        if rows_to_insert:
            print(f"🔄 Inserting {len(rows_to_insert)} records to BigQuery")
            errors = bigquery_client.insert_rows_json(table_id, rows_to_insert)
            if errors:
                print(f"❌ Failed to insert rows: {errors}")
                return jsonify({"error": "BigQuery insert failed", "details": errors}), 500
            print(f"✅ {len(rows_to_insert)} records saved to BigQuery")
        else:
            print("❌ No valid data to insert")

        # GPTの応答を返却
        return jsonify(advice_data)
    except Exception as e:
        print(f"❌ Exception occurred: {e}")
        return jsonify({"error": str(e)}), 500