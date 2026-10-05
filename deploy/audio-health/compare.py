"""Summarize exported JSONL files without loading audio or requiring dependencies."""
import argparse
import collections
import json
from pathlib import Path
from datetime import datetime, timezone


def summarize(paths):
    groups = collections.defaultdict(list)
    invalid = 0
    for path in paths:
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                invalid += 1
                continue
            if not isinstance(record, dict):
                invalid += 1
                continue
            groups[(record.get('role','unknown'),record.get('node',''),record.get('capture_id',''))].append(record)
    rows = []
    for (role,node,capture),records in groups.items():
        summaries = sorted((r for r in records if r.get('event') in ('summary','terminal_summary')),key=lambda r:r['ts_ms'])
        if not summaries:
            continue
        latest = summaries[-1]
        m = latest.get('client',latest)
        totals = m.get('totals',{})
        rates = [r.get('client',r).get('input_rate_hz',r.get('capture_rate_hz')) for r in summaries]
        rates = [v for v in rates if v is not None]
        events = collections.Counter(r.get('event') for r in records)
        rows.append({'role':role,'node':node,'capture_id':capture,'summaries':len(summaries),
                     'last_utc':datetime.fromtimestamp(latest['ts_ms']/1000,timezone.utc).isoformat(),
                     'last_seq':m.get('seq'),'rate_min_hz':round(min(rates),1) if rates else None,
                     'rate_max_hz':round(max(rates),1) if rates else None,
                     'kws_mode':m.get('kws_mode'),'kws_rtf':m.get('kws_rtf'),
                     'sequence_gaps_total':totals.get('sequence_gaps',0),
                     'kws_errors_total':totals.get('kws_errors',0),
                     'read_timeouts_total':m.get('read_timeouts_total',0),
                     'send_errors_total':m.get('send_errors_total',0),
                     'mic_dropped_samples_total':m.get('mic_dropped_samples_total',0),
                     'events':dict(events)})
    return {'groups':rows,'invalid_lines':invalid}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs',nargs='+',type=Path)
    args=parser.parse_args()
    print(json.dumps(summarize(args.logs),ensure_ascii=False,indent=2))
