# Workflows

Export each workflow from n8n (workflow menu, **Download**) and save the JSON files here:

- `1_CIB_Data_Ingestion.json`
- `2_Test_Retrieval.json`
- `4_CIB_Telegram.json`

Before committing, open each JSON file and make sure it contains no tokens, API keys, or passwords.
Search for: `token`, `sb_secret`, `password`, `apikey`.
n8n exports reference credentials by name and id only, but always check.
