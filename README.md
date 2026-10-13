# Shuttlewright GEO Audit

Check a site's AI crawl policies, page metadata, schema, llms.txt and sitemap. Save the exact HTTP status and content hash behind every check. Python 3.10+, no paid API needed.

## Run

```sh
python3 geo_audit.py --url https://pillar-fabric.onrender.com --brand "Shuttlewright" --category "AI workflow software"
python3 -m unittest test_geo -v
```

Outputs `report.json` and `evidence.csv`. The scanner uses HTTPS, pins a public DNS address before fetching, refuses redirects and limits each response to 2 MB. Audit only sites you have permission to assess. It makes four requests, not a site-wide crawl.

## Count mentions in saved engine answers

Export actual engine responses as JSON Lines with `engine`, `prompt`, `answer`, `observed_at` and optional `citations` (the URLs the engine actually returned). Then run:

```sh
python3 geo_audit.py --responses answers.jsonl --brand "Shuttlewright"
```

This reports literal brand mentions and supplied citation URLs, with response hashes. It does not call answer engines or extract invented citations from model prose. Bring your own response exports; no keys are stored here.

## Real sample

`sample-report.json` and `sample-evidence.csv` are a real four-request scan of the public site under its former name Pillar Fabric, timestamped October 10, 2026. These measure technical signals, not AI rankings. Generated buyer questions are ready to run separately. No mention/share-of-voice figures are claimed from this scan.

## Hosted product

Shuttlewright's AI Visibility Audit adds a hosted service to the free tooling. Its product page is https://pillar-agent-fabric.onrender.com/ai-visibility. This release candidate does not yet contain a verified checkout URL. Add the current checkout only after its offer, price and customer delivery are proven. The public scanner can run independently.

## License

MIT. The parser component comes from OranGEO at the pinned commit in `vendor/PROVENANCE.json`; its original MIT notice is retained in `vendor/LICENSE`. Shuttlewright's wrapper and tests are independently written. No private hosted product source, accounts, customer data or credentials are included.

## BYOK engine runner

`engine_runner.py` can run 1-3 JSON-array prompts against OpenAI chat using your own environment key. It records the exact returned answer, returned citation fields, token usage and raw-response hash. It does not infer citations or rank from prose. The API can charge your account, so an explicit `--accept-provider-charges` is required; the site scanner never calls it automatically.

```sh
# Set OPENAI_API_KEY locally using your secret manager.
python3 engine_runner.py --engine openai --prompts prompts.json --out answers.jsonl --accept-provider-charges
python3 geo_audit.py --responses answers.jsonl --brand "Your brand"
```

Plain OpenAI chat API is not the ChatGPT website and has no live search here. API output is not an equivalent test of Google AI Overviews. The runner has parser/key/charge-gate tests, but no billable live API run has been made for this release candidate.

`sample-answers.jsonl` contains one observed Google AI Overview buyer-question answer from October 10, 2026. `sample-mentions.json` records zero literal "Pillar Fabric" mentions in that answer and its displayed source URLs. This is a single session-specific observation, not a category ranking, full audit, or proof of the BYOK API runner. Source claims inside that answer are third-party output, not our endorsements.
