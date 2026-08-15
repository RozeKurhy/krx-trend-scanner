"""종목별 일봉 Parquet 캐시.

주봉/월봉은 캐시하지 않는다(일봉에서 runtime에 생성한다).
Atomic write 및 write verification을 지원하여 파일 손상 및 부분 저장을 원천 차단한다.
"""

from __future__ import annotations

import os
from pathlib import Path
import uuid

import pandas as pd

from trend_scanner.data.validator import validate_ohlcv

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
        """Parquet 캐시를 원자적(Atomic)으로 저장하고 검증한다.

        [원자적 쓰기 절차]:
        1. 대상 디렉토리 내에 고유한 임시 파일(.{ticker}.parquet.tmp_{uuid})을 생성한다.
        2. 임시 파일에 parquet을 기록한다.
        3. 기록된 임시 파일을 다시 읽어들여(Read-Back) validate_ohlcv 및 정렬/고유성을 검증한다.
        4. 검증이 통과하면 os.replace()를 통해 최종 경로로 atomic rename한다.
        5. 중간 오류 발생 시 임시 파일을 삭제하고 기존 최종 캐시는 100% 보존한다.
        """
        final_path = self._path(ticker)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        temp_path = self.base_dir / f".{ticker}.parquet.tmp_{uuid.uuid4().hex}"
        try:
            # 1. 임시 파일에 기록
            df.to_parquet(temp_path)

            # 2. 임시 파일 다시 읽기 및 검증 (Read-Back Validation)
            read_back = pd.read_parquet(temp_path)
            validate_ohlcv(read_back)

            if not read_back.index.is_monotonic_increasing:
                raise ValueError(f"저장된 캐시 인덱스가 오름차순 정렬되지 않았습니다 ({ticker}).")
            if not read_back.index.is_unique:
                raise ValueError(f"저장된 캐시 인덱스에 중복 거래일이 존재합니다 ({ticker}).")
            if len(read_back) != len(df):
                raise ValueError(f"저장 전후 행 수가 일치하지 않습니다 ({len(df)} != {len(read_back)}).")

            # 3. 원자적 교체 (Atomic Replace)
            os.replace(temp_path, final_path)
        except Exception:
            # 오류 발생 시 임시 파일 정리 및 예외 전파 (기존 final_path 보존)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    def latest_date(self, ticker: str) -> pd.Timestamp | None:
        df = self.load(ticker)
        if df is None or df.empty:
            return None
        return df.index.max()

    def list_cached_tickers(self) -> list[str]:
        """캐시 디렉토리에 존재하는 모든 종목코드(.parquet 파일 stem) 목록을 반환한다."""
        if not self.base_dir.exists():
            return []
        # . 으로 시작하는 hidden / temp 파일은 제외
        return sorted([p.stem for p in self.base_dir.glob("*.parquet") if p.is_file() and not p.name.startswith(".")])
