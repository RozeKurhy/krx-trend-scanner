"""종목별 일봉 Parquet 캐시.

주봉/월봉은 캐시하지 않는다(일봉에서 runtime에 생성한다).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DEFAULT_CACHE_DIR = Path("data/raw/stocks")


class ParquetCache:
    def __init__(self, base_dir: Path | str = DEFAULT_CACHE_DIR):
        self.base_dir = Path(base_dir)

    def _path(self, ticker: str) -> Path:
        return self.base_dir / f"{ticker}.parquet"

    def load(self, ticker: str) -> pd.DataFrame | None:
        path = self._path(ticker)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def save(self, ticker: str, df: pd.DataFrame) -> None:
        path = self._path(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)

    def latest_date(self, ticker: str) -> pd.Timestamp | None:
        df = self.load(ticker)
        if df is None or df.empty:
            return None
        return df.index.max()

    def list_cached_tickers(self) -> list[str]:
        """캐시 디렉토리에 존재하는 모든 종목코드(.parquet 파일 stem) 목록을 반환한다."""
        if not self.base_dir.exists():
            return []
        return sorted([p.stem for p in self.base_dir.glob("*.parquet") if p.is_file()])
