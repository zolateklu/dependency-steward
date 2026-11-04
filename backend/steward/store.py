"""Revision-checked documents. SQLite is local only; SQL/Postgres and Firestore are durable options."""

import copy
import json

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, insert, select, update
from sqlalchemy.exc import IntegrityError


class Conflict(Exception):
    pass


class SQLStore:
    def __init__(self, url: str):
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(url, pool_pre_ping=True)
        meta = MetaData()
        self.table = Table(
            "steward_documents",
            meta,
            Column("id", String(240), primary_key=True),
            Column("revision", Integer, nullable=False),
            Column("body", Text, nullable=False),
        )
        meta.create_all(self.engine)

    def get(self, key):
        with self.engine.connect() as conn:
            row = conn.execute(select(self.table).where(self.table.c.id == key)).mappings().first()
            return (row["revision"], json.loads(row["body"])) if row else (0, None)

    def put(self, key, revision, body):
        encoded = json.dumps(body, allow_nan=False)
        try:
            with self.engine.begin() as conn:
                if revision == 0:
                    conn.execute(insert(self.table).values(id=key, revision=1, body=encoded))
                else:
                    result = conn.execute(
                        update(self.table)
                        .where(self.table.c.id == key, self.table.c.revision == revision)
                        .values(revision=revision + 1, body=encoded)
                    )
                    if result.rowcount != 1:
                        raise Conflict("State changed; refresh before retrying")
        except IntegrityError as exc:
            raise Conflict("State changed; refresh before retrying") from exc
        return revision + 1

    def list(self, prefix):
        with self.engine.connect() as conn:
            rows = conn.execute(select(self.table).where(self.table.c.id.startswith(prefix))).mappings()
            return [json.loads(row["body"]) for row in rows]


class FirestoreStore:
    def __init__(self, project, collection, credentials=None):
        from google.cloud import firestore

        self.client = firestore.Client(project=project, credentials=credentials)
        self.collection = self.client.collection(collection)

    def get(self, key):
        snap = self.collection.document(key).get()
        data = snap.to_dict() if snap.exists else None
        return (data["revision"], data["body"]) if data else (0, None)

    def put(self, key, revision, body):
        from google.cloud import firestore

        ref = self.collection.document(key)

        @firestore.transactional
        def write(transaction):
            snap = ref.get(transaction=transaction)
            current = snap.to_dict()["revision"] if snap.exists else 0
            if current != revision:
                raise Conflict("State changed; refresh before retrying")
            transaction.set(ref, {"revision": revision + 1, "body": copy.deepcopy(body)})

        write(self.client.transaction())
        return revision + 1

    def list(self, prefix):
        query = (
            self.collection.order_by("__name__")
            .start_at({"__name__": self.collection.document(prefix)})
            .end_before({"__name__": self.collection.document(prefix + "\uf8ff")})
        )
        return [snap.to_dict()["body"] for snap in query.stream()]
