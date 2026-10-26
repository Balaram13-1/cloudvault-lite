import boto3
from botocore.exceptions import ClientError

BUCKET = "cloud-vaultbucket"
s3 = boto3.client(
    "s3",
    region_name="ap-south-1",
    endpoint_url="https://s3.ap-south-1.amazonaws.com",
)

try:
    # 1. Create a small local file and upload it
    with open("hello.txt", "w") as f:
        f.write("Hello from boto3!")
    with open("hello.txt", "rb") as f:
        s3.upload_fileobj(f, BUCKET, "hello.txt")
    print("Uploaded hello.txt")

    # 2. List everything in the bucket
    resp = s3.list_objects_v2(Bucket=BUCKET)
    for obj in resp.get("Contents", []):
        print(f"{obj['Key']}  ({obj['Size']} bytes)")

    # 3. Make a download link that expires in 60 seconds
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": "hello.txt"},
        ExpiresIn=60,
    )
    print("Download link (valid 60s):", url)

    input("Open the link in your browser, then press Enter to delete the file...")

    # 4. Delete it
    s3.delete_object(Bucket=BUCKET, Key="hello.txt")
    print("Deleted hello.txt")

except ClientError as e:
    print("AWS error:", e.response["Error"]["Code"])
