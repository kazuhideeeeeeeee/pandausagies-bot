import json
import unittest
from urllib.parse import parse_qs,urlparse

from pandausagies_v2.x_ingestion import XReadConfig,run_x_read
from pandausagies_v2.x_read import XReadClient,XReadError,classify_mention


class Transport:
    def __init__(self,responses): self.responses=list(responses);self.urls=[]
    def get(self,url,headers,timeout):
        self.urls.append(url); item=self.responses.pop(0)
        if isinstance(item,Exception): raise item
        status,payload,*rest=item;return status,(rest[0] if rest else {}),json.dumps(payload).encode() if not isinstance(payload,bytes) else payload


class FakeDb:
    def __init__(self): self.cursor=None;self.identity=None;self.ids=set();self.rows=[]
    def select(self,table,query=""):
        if table=="x_read_cursors": return [self.cursor] if self.cursor else []
        if table=="x_account_identities": return [self.identity] if self.identity else []
        return []
    def insert(self,table,payload,upsert=False):
        if table=="x_read_cursors": self.cursor={**payload};return [payload]
        if table=="x_account_identities": self.identity={**payload};return [payload]
    def patch(self,table,query,payload):
        target=self.cursor if table=="x_read_cursors" else self.identity;target.update(payload);return [target]
    def rpc(self,name,payload):
        post=payload["p_mention"]; fresh=post["x_post_id"] not in self.ids
        if fresh:self.ids.add(post["x_post_id"]);self.rows.append(payload)
        return fresh


USER={"data":{"id":"99","name":"Panda","username":"pandausagies"}}
PAGE={"data":[{"id":"101","author_id":"1","text":"パン食べた？","created_at":"2026-08-24T01:00:00Z","conversation_id":"101","referenced_posts":[]}],"includes":{"users":[{"id":"1","name":"Guest","username":"guest_one"}]},"meta":{"newest_id":"101"}}


class XReadTests(unittest.TestCase):
    def test_read_client_has_no_write_surface(self):
        client=XReadClient("token",Transport([]))
        for name in ("create_post","reply","like","repost","follow","dm","delete","hide_reply"):
            self.assertFalse(hasattr(client,name))

    def test_lookup_and_mentions_use_get_since_id_and_pagination(self):
        first={**PAGE,"meta":{"newest_id":"101","next_token":"next"}}
        second={"data":[],"includes":{"users":[]},"meta":{}}
        transport=Transport([(200,USER),(200,first),(200,second)]);client=XReadClient("token",transport)
        self.assertEqual(client.lookup_user("@pandausagies")["id"],"99")
        page=client.get_mentions("99",since_id="100",max_results=5,max_pages=2,total_limit=10)
        self.assertEqual(len(page.mentions),1);query=parse_qs(urlparse(transport.urls[1]).query)
        self.assertEqual(query["since_id"],["100"]);self.assertEqual(parse_qs(urlparse(transport.urls[2]).query)["pagination_token"],["next"])

    def test_error_classes(self):
        for status,kind in ((401,"authentication"),(403,"permission"),(429,"rate_limited"),(500,"server")):
            client=XReadClient("token",Transport([(status,{},{"retry-after":"60"})]))
            with self.assertRaises(XReadError) as caught: client.lookup_user("pandausagies")
            self.assertEqual(caught.exception.kind,kind)
        with self.assertRaises(XReadError): XReadClient("token",Transport([(200,b"bad")])).lookup_user("pandausagies")

    def test_empty_and_classification(self):
        self.assertEqual(classify_mention("自動返信しないで"),("opted_out",True))
        self.assertEqual(classify_mention("法律相談です")[0],"needs_human")
        self.assertEqual(classify_mention("今すぐ稼げる")[0],"spam")
        self.assertEqual(classify_mention("パン食べた？")[0],"candidate")

    def test_ingestion_is_idempotent_and_cursor_advances_only_on_success(self):
        cfg=XReadConfig("staging","pandausagies",True,False,False,False,True,10,2);db=FakeDb()
        one=run_x_read(XReadClient("token",Transport([(200,USER),(200,PAGE)])),db,cfg,True)
        self.assertEqual((one["stored"],one["duplicates"]),(1,0));self.assertEqual(db.cursor["last_seen_mention_id"],"101")
        duplicate=run_x_read(XReadClient("token",Transport([(200,PAGE)])),db,cfg,False)
        self.assertEqual((duplicate["stored"],duplicate["duplicates"]),(0,1));self.assertEqual(len(db.rows),1)

    def test_failure_does_not_advance_cursor(self):
        cfg=XReadConfig("staging","pandausagies",True,False,False,False,True);db=FakeDb();db.cursor={"key":"mentions","last_seen_mention_id":"100","api_call_count":0,"error_count":0};db.identity={"handle":"pandausagies","x_user_id":"99","current_username":"pandausagies","display_name":"Panda"}
        result=run_x_read(XReadClient("token",Transport([(429,{},{"retry-after":"300"})])),db,cfg)
        self.assertEqual(result["status"],"safe_stopped");self.assertEqual(db.cursor["last_seen_mention_id"],"100");self.assertIsNotNone(db.cursor["retry_after"])


if __name__=="__main__":unittest.main()
