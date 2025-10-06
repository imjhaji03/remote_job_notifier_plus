import os, re, email, datetime
from imapclient import IMAPClient

def fetch_links_from_label(host, port, user, pw, label, days=1):
    try:
        server = IMAPClient(host, port=port, ssl=True)
        server.login(user, pw)
        server.select_folder(label, readonly=True)
        since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%d-%b-%Y")
        msgs = server.search(['SINCE', since])
        resp = server.fetch(msgs, ['RFC822'])
        links = []
        rx = re.compile(rb'https?://[^\s<>\"]+')
        for uid, msg in resp.items():
            raw = msg[b'RFC822']
            m = email.message_from_bytes(raw)
            parts = [m.get_payload(decode=True)] if not m.is_multipart() else [p.get_payload(decode=True) for p in m.get_payload() if p.get_content_maintype() in ('text','multipart')]
            for p in parts:
                if not p: continue
                found = rx.findall(p)
                for f in found:
                    u = f.decode('utf-8', errors='ignore')
                    if 'unsubscribe' in u.lower(): 
                        continue
                    links.append(u)
        server.logout()
        # dedupe preserving order
        seen=set(); out=[]
        for u in links:
            if u not in seen:
                seen.add(u); out.append(u)
        return out
    except Exception as e:
        print("IMAP ingest disabled or failed:", e)
        return []
