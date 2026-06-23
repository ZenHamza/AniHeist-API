#!/bin/bash
uvicorn consumet_api.reanime_api:app --host 0.0.0.0 --port 4000 &
sleep 2
uvicorn src.api:app --host 0.0.0.0 --port 8000 --limit-concurrency 10
