import json

with open('tests/fixtures/ingest/linux_transcript.json') as f:
    fixture = json.load(f)

segs = fixture['transcript']
for seg in segs[:5]:
    duration = seg['end_time'] - seg['start_time']
    words = len(seg['text'].split())
    wpm = (words / duration) * 60
    print(f"  [{seg['start_time']:.0f}-{seg['end_time']:.0f}s] words={words}, duration={duration:.0f}s, WPM={wpm:.1f}")

text = "The Linux file system is organized as a hierarchical tree starting from the root directory represented by a forward slash the ls command lists directory contents."
words = len(text.split())
print(f"Test segment: words={words}, WPM over 30s = {words/30*60:.1f}")

