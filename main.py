from flask import Flask, jsonify, request
from google.cloud import bigquery
from dotenv import load_dotenv
import os
import openai
print(f"✅ openai version: {openai.__version__}")
from openai import OpenAI
import json
from datetime import date
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
    participant_id = request.args.get("id")  # 例: /?id=user123
    try:
        print("🔄 Initializing OpenAI client...")
        openai_client = OpenAI(
            api_key=api_key, 
            timeout=httpx.Timeout(300.0, read=60.0, write=200.0, connect=20.0)
        )
        print("✅ OpenAI client initialized")

        bigquery_client = bigquery.Client()
        query = f"""
WITH sleep AS (
  SELECT 
    summary_date,
    participant_uid,
    score,
    total,
    light,
    rem,
    deep,
    hr_average,
    hr_lowest,
    rmssd
  FROM `sic-ouraring-verify.gcube.sleep`
  WHERE total >= 3600
),
activity AS (
  SELECT 
    summary_date,
    participant_uid,
    steps,
    high,
    medium,
    low,
    inactive,
  	cal_total
  FROM `sic-ouraring-verify.gcube.activity`
  WHERE non_wear <= 14400
)

SELECT 
  s.summary_date AS date,
  s.score AS sleep_score,
  s.total AS total_sleep_seconds,
  s.light AS light_sleep_seconds,
  s.rem AS rem_sleep_seconds,
  s.deep AS deep_sleep_seconds,
  s.hr_average AS sleep_heart_rate_average,
  s.hr_lowest AS sleep_heart_rate_lowest,
  s.rmssd AS sleep_rmssd,
  a.steps,
  a.high AS high_intensity_activity_minutes,
  a.medium AS medium_intensity_activity_minutes,
  a.low AS low_intensity_activity_minutes,
  a.inactive AS inactivity_minutes,
  a.cal_total AS calorie_total
FROM sleep s
LEFT JOIN activity a
  ON s.summary_date = a.summary_date AND s.participant_uid = a.participant_uid
WHERE s.summary_date BETWEEN "2025-07-01" AND "2025-07-31" {"AND s.participant_uid = @participant_id" if participant_id else ""}
ORDER BY s.participant_uid ASC,s.summary_date ASC
LIMIT 100
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("participant_id", "STRING", participant_id)
            ] if participant_id else []
        )
        query_job = bigquery_client.query(query, job_config=job_config)
        results = query_job.result()
        data_list = [dict(row.items()) for row in results]

        prompt_data = "\n".join([str(row) for row in data_list])
        print(f"📋 Prompt data prepared: {prompt_data}")

        try:
            print(f"🔄 Sending request to OpenAI...")
            # OpenAI GPT-4o にリクエスト
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": f"""あなたは健康状態を管理するベテランのアドバイザーです。
データからその人の健康状態を知り、適切なアドバイスをすることがあなたの仕事です。
あなたは生体情報を持っています。
sleep_scoreは、数値が高いほど質の高い睡眠ができていることを意味します。
deep_sleep_secondsはN3（最も深いノンレム睡眠）状態の深い睡眠時間(秒)を表します。light_sleep_secondsはN2（中間の深さのノンレム睡眠）もしくはN1（浅いノンレム睡眠）状態の浅い睡眠時間(秒)、rem_sleep_secondsはREM（レム睡眠）状態の睡眠時間(秒)を表します。total_sleep_secondsは合計睡眠時間(秒)を表します。
sleep_heart_rate_averageは睡眠中の心拍数の平均値を表します。
sleep_heart_rate_lowestは睡眠中の心拍数の最低値を表します。
sleep_rmssdは睡眠中の心拍数の変動の平均を表します。
stepsは1日の歩数を表します。
high_intensity_activity_minutesは自転車に乗る程度の高強度運動時間(分)、medium_intensity_activity_minutesはウォーキング程度の中強度運動時間(分)、low_intensity_activity_minutesは立っている程度の低強度運動時間(分)、inactive_minutesは座っている程度の非活動時間(分)を表します。
calorie_totalは1日のカロリー消費量を表します。

これから扱う生体情報には、データ更新が途中で止まっている可能性があり、
欠損値や連続した同じ値が含まれているかもしれませんが、
使える範囲でデータ分析を行い、必要以上に気にしすぎないでください。
                 
以下の形式のJSONで回答してください：
{{
    "id": "{participant_id or 'unknown'}",
    "sleep_analysis": "睡眠に関する分析とアドバイス",
    "activity_analysis": "運動に関する分析とアドバイス",
    "recommendations": "具体的な改善提案",
    "overall_assessment": "総合的な評価"
}}
                 
idは指定した文字列をそのままにして変更しないでください。
最終応答は、"{{"で始まり"}}"で終わる。または"["で始まり"]"で終わるJSONのみを出力し、JSON以外の文字は一切応答に含めないでください。"""},
                    {"role": "user", "content": f"""ある企業の従業員の1ヶ月分の生体情報を持っています。
生体情報を使って、分析結果の回答を作成してください。

睡眠に関する分析とアドバイスには、睡眠時の生体情報の分析結果と、結果をもとにしたポジティブなアドバイスを根拠も踏まえて説明してください。
運動に関する分析とアドバイスには、運動時の生体情報の分析結果と、結果をもとにしたポジティブなアドバイスを根拠も踏まえて説明してください。
具体的な改善提案には、例えば、睡眠時間がこれまでより短いなら、もう少し長く寝る工夫を促すなど、具体的にポジティブな方向性を伝えてください。
総合的な評価には、根拠やポジティブなメッセージを盛り込み、過ごし方について総合的にまとめてください。
相手は専門家ではなく一般の人なので、数値だけに頼らず、より分かりやすい文章で説明を行ってください。
                     それぞれ400～600文字程度の自然な日本語で提案を作成してください。
                     \n生体情報：\n\n{prompt_data}"""}
                ]
            )
            print(f"✅ OpenAI response received")

        except openai.APITimeoutError as e:
            print(f"❌ OpenAI API timeout error: {e}", flush=True)
            return jsonify({"error": "OpenAI API timeout"}), 408
        except Exception as e:
            print(f"❌ OpenAI API error: {e}")
            return jsonify({"error": f"OpenAI API error: {str(e)}"}), 500

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