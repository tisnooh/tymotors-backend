"""Preview or apply the safe defaults required by the secured catalogue.

Usage:
  python migrations/001_secure_catalog.py          # dry run
  python migrations/001_secure_catalog.py --apply  # apply after a database backup
"""

import argparse
import os

from dotenv import load_dotenv
from pymongo import MongoClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    client = MongoClient(os.environ["MONGO_URL"])
    products = client[os.environ["DB_NAME"]].products
    legacy_query = {"status": {"$exists": False}}
    count = products.count_documents(legacy_query)
    print(f"Legacy products found: {count}")
    if not args.apply:
        print("Dry run only. Back up MongoDB, complete product data, then rerun with --apply.")
        return
    result = products.update_many(
        legacy_query,
        {"$set": {
            "status": "draft",
            "is_verified": False,
            "rating": None,
            "review_count": 0,
            "badges": [],
            "compatibilities": [],
            "package_contents": [],
        }},
    )
    print(f"Products moved to draft: {result.modified_count}")


if __name__ == "__main__":
    main()

