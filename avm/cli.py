from __future__ import annotations

import argparse
import json
import sys

from .collectors.base import MissingApiKeyError
from .collectors.ecos_rates import collect_rates
from .collectors.molit_generic import TYPE_CONFIGS, collect_trades
from .collectors.vworld_geocode import collect_geocodes
from .db import init_db
from .features import build_feature_frame
from .mapping import build_map_html
from .model import load_model, predict_one, save_model, train


def cmd_collect_trades(args: argparse.Namespace) -> None:
    saved = collect_trades(
        property_type=args.type,
        region_code=args.region,
        start_ymd=args.start,
        end_ymd=args.end,
        region_name=args.region_name or "",
    )
    label = TYPE_CONFIGS[args.type].label
    print(f"{label} 실거래가 {saved}건 저장 완료.")


def cmd_collect_geocode(_: argparse.Namespace) -> None:
    saved = collect_geocodes()
    print(f"좌표 {saved}건 신규 저장 완료.")


def cmd_collect_rates(args: argparse.Namespace) -> None:
    saved = collect_rates(start=args.start, end=args.end)
    print(f"기준금리 {saved}건 신규 저장 완료.")


def cmd_features_build(args: argparse.Namespace) -> None:
    df = build_feature_frame()
    out_path = args.out
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"피처 {len(df)}행 -> {out_path}")


def cmd_train(args: argparse.Namespace) -> None:
    df = build_feature_frame()
    result = train(df)
    path = save_model(result, name=args.name)
    print(f"최적 모델: {result['best_name']} (train={result['n_train']}, test={result['n_test']})")
    if result["dropped_columns"]:
        print(f"결측으로 제외된 피처: {', '.join(result['dropped_columns'])}")
    print(json.dumps(result["all_metrics"], ensure_ascii=False, indent=2))
    print(f"저장 위치: {path}")


def cmd_map(args: argparse.Namespace) -> None:
    html = build_map_html()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"지도 저장 완료 -> {args.out}")


def cmd_predict(args: argparse.Namespace) -> None:
    with open(args.input, encoding="utf-8") as f:
        features = json.load(f)
    model = load_model(name=args.name)
    price = predict_one(model, features)
    print(f"추정 거래금액: {price:,.0f} 원")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="avm", description="부동산 자동산정모형(AVM) CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="데이터 수집")
    collect_sub = collect.add_subparsers(dest="source", required=True)

    p_trades = collect_sub.add_parser("trades", help="매매 실거래가 수집")
    p_trades.add_argument(
        "--type",
        choices=list(TYPE_CONFIGS),
        default="apt",
        help="부동산 유형 (apt=아파트, rh=연립다세대, sh=단독/다가구, offi=오피스텔). 기본값 apt",
    )
    p_trades.add_argument("--region", required=True, help="법정동코드 5자리 (예: 11110)")
    p_trades.add_argument(
        "--region-name",
        default="",
        help="주소 조합용 시도/시군구명 (예: '서울특별시 종로구'). 생략 시 API 응답의 estateAgentSggNm을 사용",
    )
    p_trades.add_argument("--start", required=True, help="시작 계약월 YYYYMM")
    p_trades.add_argument("--end", required=True, help="종료 계약월 YYYYMM")
    p_trades.set_defaults(func=cmd_collect_trades)

    p_geocode = collect_sub.add_parser("geocode", help="trades 주소 지오코딩")
    p_geocode.set_defaults(func=cmd_collect_geocode)

    p_rates = collect_sub.add_parser("rates", help="한국은행 기준금리 수집")
    p_rates.add_argument("--start", required=True, help="시작월 YYYYMM")
    p_rates.add_argument("--end", required=True, help="종료월 YYYYMM")
    p_rates.set_defaults(func=cmd_collect_rates)

    features = sub.add_parser("features", help="피처 생성")
    features_sub = features.add_subparsers(dest="action", required=True)
    p_build = features_sub.add_parser("build", help="피처 테이블 생성 후 CSV로 저장")
    p_build.add_argument("--out", default="data/features.csv")
    p_build.set_defaults(func=cmd_features_build)

    p_map = sub.add_parser("map", help="지오코딩된 거래를 지도 HTML로 내보내기")
    p_map.add_argument("--out", default="data/map.html")
    p_map.set_defaults(func=cmd_map)

    p_train = sub.add_parser("train", help="모델 학습")
    p_train.add_argument("--name", default="avm_model")
    p_train.set_defaults(func=cmd_train)

    p_predict = sub.add_parser("predict", help="모델로 가격 추정")
    p_predict.add_argument("--input", required=True, help="피처 JSON 파일 경로")
    p_predict.add_argument("--name", default="avm_model")
    p_predict.set_defaults(func=cmd_predict)

    return parser


def main(argv=None) -> int:
    init_db()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except MissingApiKeyError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
