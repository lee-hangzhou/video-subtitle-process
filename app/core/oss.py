import oss2

from app.core import settings


class OssClient:
    def __init__(self):
        self.auth = oss2.Auth(
            settings.alibaba.access_key_id,
            settings.alibaba.access_key_secret,
        )
        self.bucket = oss2.Bucket(
            self.auth,
            settings.alibaba.oss_endpoint,
            settings.alibaba.oss_bucket_name,
        )

    def upload_file(self, local_path: str, oss_key: str):
        self.bucket.put_object_from_file(key=oss_key, filename=local_path)

    def sign_url(self, oss_key: str):
        return self.bucket.sign_url('GET', oss_key, 3600)
