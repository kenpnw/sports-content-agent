import argparse
import json

from config import OUTPUT_DIR
from ingestion.nba_live import fetch_today_nba_postgame_data
from webapp.app import run as run_dashboard
from workflows.nba_postgame import run_nba_postgame_workflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sports content agent CLI and control room."
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run the local web control room.",
    )
    source_group = parser.add_mutually_exclusive_group(required=False)
    source_group.add_argument(
        "--input",
        help="Path to an NBA postgame JSON file.",
    )
    source_group.add_argument(
        "--fetch-today",
        action="store_true",
        help="Fetch today's NBA results from the NBA live data feed.",
    )
    parser.add_argument(
        "--team",
        help="Optional team filter when using --fetch-today, for example LAL or Warriors.",
    )
    parser.add_argument(
        "--save-input",
        action="store_true",
        help="Save the fetched normalized input JSON alongside generated output.",
    )
    parser.add_argument(
        "--output-dir",
        default=OUTPUT_DIR,
        help="Directory for generated content packages.",
    )
    args = parser.parse_args()
    if not args.serve and not args.input and not args.fetch_today:
        parser.error("Either use --serve or provide --input / --fetch-today.")
    return args


def main() -> None:
    args = parse_args()
    if args.serve:
        run_dashboard()
        return

    input_path = args.input
    selection_context = None
    if args.fetch_today:
        fetch_result = fetch_today_nba_postgame_data(
            output_dir=args.output_dir,
            team_filter=args.team,
            save_input=args.save_input,
        )
        input_path = fetch_result["input_path"]
        selection_context = fetch_result.get("selection")
    summary = run_nba_postgame_workflow(
        input_path,
        args.output_dir,
        selection_context=selection_context,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
