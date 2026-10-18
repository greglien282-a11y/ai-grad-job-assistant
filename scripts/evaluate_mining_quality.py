"""Offline, supplied synthetic outputs only. No DB/env/Provider/credentials."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.mining_quality_evaluation import evaluate,read_json,markdown_report
from app.mining_quality_review import templates,review_packet,summarize_reviews,reviews_markdown


def main():
    parser=argparse.ArgumentParser(description='Offline DRAFT-reference checks; not real model quality')
    parser.add_argument('--outputs',type=Path,required=True)
    parser.add_argument('--split',choices=['development','holdout'],default='development')
    parser.add_argument('--reviews',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    bundle=read_json(args.outputs);report=evaluate(bundle,split=args.split)
    artifacts={'metrics.json':json.dumps(report,ensure_ascii=False,indent=2)+'\n',
        'metrics.md':markdown_report(report),
        'review-template.json':json.dumps(templates(report),ensure_ascii=False,indent=2)+'\n',
        'review-packet.md':review_packet(report,bundle)}
    if args.reviews:
        reviews=summarize_reviews(report,bundle,read_json(args.reviews))
        artifacts.update({'reviews.json':json.dumps(reviews,ensure_ascii=False,indent=2)+'\n','reviews.md':reviews_markdown(reviews)})
    # Refuse existing dirs/reparse targets; never overwrite historic evidence.
    # This CLI processes local fictional files, not a protected real-data store.
    if args.output_dir.exists() or args.output_dir.is_symlink(): raise ValueError()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    for name,content in artifacts.items():
        with (args.output_dir/name).open('x',encoding='utf8',newline='\n') as file: file.write(content)
    print('OFFLINE_QUALITY_REPORT_WRITTEN; labels=DRAFT; human_scores=unreviewed; real_quality=null; provider_requests=0')


if __name__=='__main__':
    try: main()
    except Exception:
        raise SystemExit('QUALITY_EVALUATION_STOPPED: invalid input or report destination; no inference attempted.') from None
