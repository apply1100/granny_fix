import urllib.request
import urllib.parse
import sys
token = '8282015972:AAHTTRpiQCyS75WkLLDIethbgWBNXpOw1IU'
chat_ids = ['-1001748530937', '-1003643470349']
alert_text = '''BitMEX 테스트 알림 작동 확인

안녕하세요! 
서버 고정 환경변수에 등록해주신 사진을 보고, 봇이 두 방으로 동시에 알림을 잘 보내는지 원격 확인을 위해 제가 테스트 메세지를 발송했습니다.

이 메세지가 두 방 모두에서 보인다면 완벽하게 세팅된 것입니다! 👵🏻'''

for chat_id in chat_ids:
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = urllib.parse.urlencode({'chat_id': chat_id, 'text': alert_text}).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req) as response:
            print(f'Successfully sent to {chat_id}')
    except Exception as e:
        print(f'Failed to send to {chat_id}: {e}')
sys.exit(0)
