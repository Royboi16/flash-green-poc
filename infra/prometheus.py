global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "bot"
    static_configs:
      - targets: ["bot:8000"]
