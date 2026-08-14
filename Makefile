# 常用指令的捷徑。全部走 uv，不需要先 activate 虛擬環境。
#
# uv 沒有內建 task runner，所以用 make 當薄薄一層包裝。
# 不想用 make 的話，直接看每個 target 底下那行 uv 指令即可。

.DEFAULT_GOAL := help
.PHONY: help setup build test check lint fmt all clean

help:  ## 顯示這份說明
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup:  ## 建立虛擬環境並安裝相依（含 dev）
	uv sync

build:  ## 從 src/ 重新產生兩份 notebook（ARGS="--project-id X --speaker Y"）
	uv run python poc/build_notebook.py $(ARGS)

test:  ## 跑全部測試（離線、不呼叫 API、不花錢）
	uv run pytest

check:  ## 環境健檢（會呼叫真實 API，需要網路與 GCP 認證）
	uv run python poc/check_env.py

lint:  ## 靜態檢查
	uv run ruff check poc/

fmt:  ## 自動修正可修的問題
	uv run ruff check --fix poc/

all: build test  ## 改完程式碼後的標準流程：重新產生 notebook + 跑測試

clean:  ## 移除虛擬環境與快取
	rm -rf .venv .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
