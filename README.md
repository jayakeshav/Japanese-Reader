# Japanese Reader

A Streamlit app to read Japanese text with inline Romaji ruby, optional line-by-line English translation, and inline Kanji meaning tooltips.

## Local Run

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Start the app:

```bash
python3 -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

3. Open in browser:

- `http://localhost:8501`

## Deploy To Streamlit Community Cloud

1. Create a GitHub repository and push these files:
   - `app.py`
   - `requirements.txt`
   - `README.md`
2. Sign in to Streamlit Community Cloud.
3. Click **Create app**.
4. Select your GitHub repository, branch, and set main file path to `app.py`.
5. Click **Deploy**.

## Notes

- `unidic-lite` is included to avoid system-level MeCab dictionary setup issues in cloud environments.
- Translation and dictionary lookup features require outbound internet access.
