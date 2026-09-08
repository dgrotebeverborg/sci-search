from io import BytesIO

import boto3
import pytest
from botocore.config import Config

from sci_search.infrastructure.s3_blobs import S3BlobStore
from tests.blob_contract import (
    assert_bounded_and_hash_verified_put,
    assert_round_trip_and_deduplication,
)

ENDPOINT = "http://127.0.0.1:59000"
BUCKET = "sci-search-test"


@pytest.fixture
def s3_client():
    client = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id="sci_search",
        aws_secret_access_key="sci_search_test_password",
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    try:
        client.create_bucket(Bucket=BUCKET)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    listed = client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    for item in listed:
        client.delete_object(Bucket=BUCKET, Key=item["Key"])
    return client


@pytest.fixture
def store(s3_client) -> S3BlobStore:
    return S3BlobStore(s3_client, BUCKET)


def test_minio_reuses_the_blob_round_trip_and_dedup_contract(store: S3BlobStore) -> None:
    assert_round_trip_and_deduplication(store)
    first = store.put(BytesIO(b"scientific paper"), 1024, content_type="application/pdf")

    assert not first.key.startswith(("http://", "https://", "s3://"))
    assert not hasattr(first, "url")


def test_minio_reuses_bounded_and_hash_verified_put_contract(store: S3BlobStore) -> None:
    assert_bounded_and_hash_verified_put(store)


def test_minio_objects_remain_private_and_metadata_is_verified(
    store: S3BlobStore,
    s3_client,
) -> None:
    reference = store.put(BytesIO(b"paper"), 100, content_type="application/pdf")

    metadata = s3_client.head_object(Bucket=BUCKET, Key=reference.key)
    assert metadata["Metadata"]["sha256"] == reference.sha256
    assert int(metadata["Metadata"]["size"]) == reference.size
    grants = s3_client.get_object_acl(Bucket=BUCKET, Key=reference.key)["Grants"]
    assert all(grant["Grantee"].get("Type") == "CanonicalUser" for grant in grants)
