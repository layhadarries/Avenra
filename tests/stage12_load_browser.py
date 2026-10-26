"""Small bounded localhost smoke load; not production capacity or delivery proof."""
from concurrent.futures import ThreadPoolExecutor
import time
import urllib.error
import urllib.request
from stage0_browser import main


def exercise(page,staff,base,env):
    paths=[('/survivor/help.html',{},200),('/api/diary',{'X-Device-Token':'demo-device'},423),('/api/alerts',{},401)]*32
    def request(item):
        path,headers,expected=item; started=time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers),timeout=10) as response:
                status=response.status; response.read()
        except urllib.error.HTTPError as response:
            with response: status=response.code; response.read()
        return status,expected,time.monotonic()-started
    with ThreadPoolExecutor(max_workers=8) as workers: results=list(workers.map(request,paths))
    assert all(actual==expected for actual,expected,_ in results),'Smoke load changed an access boundary or returned an unexpected error'
    durations=sorted(duration for _,_,duration in results)
    p95=durations[int(.95*(len(durations)-1))]
    assert p95<5 and durations[-1]<10,'Bounded local smoke budget exceeded (not a production SLA)'
    print('PASS: 96 localhost requests / 8 concurrent clients; public and locked/signed-out boundaries preserved.')
    print('LOCAL ONLY: p95=%.3fs max=%.3fs; no provider calls, emergency delivery or production throughput measured.'%(p95,durations[-1]))


if __name__=='__main__': main(exercise)
