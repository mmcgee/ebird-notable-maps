# eBird Notable Maps

Static HTML maps of recent notable eBird observations around a fixed center, built by GitHub Actions and served via GitHub Pages.

- Public site root: `https://<username>.github.io/ebird-notable-maps/`
- Latest map: `https://<username>.github.io/ebird-notable-maps/maps/latest.html`

## Bring your own key

This project **never** hardcodes an API key. To run builds:

- In GitHub Actions, set a repository secret named `EBIRD_API_KEY`  
  Settings → Secrets and variables → Actions → New repository secret

- For local testing or Colab, set `EBIRD_API_KEY` in your environment:
  ```python
  import os
  os.environ["EBIRD_API_KEY"] = "your-real-key"
