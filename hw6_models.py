import os

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier

PROJECT_ID = os.environ.get("PROJECT_ID", "adefifp22909")
INSTANCE = os.environ.get("INSTANCE", "adefifp22909:us-central1:hw5-db-instance")
DB_NAME = os.environ.get("DB_NAME", "cs528_hw5")
DB_USER = os.environ.get("DB_USER", "root")
DB_SECRET = os.environ.get("DB_SECRET", "hw6-db-pass")
BUCKET = os.environ.get("BUCKET", "cs528-pagerank-eddielu-1790373540")
OUT_PREFIX = os.environ.get("OUT_PREFIX", "hw6")
SEED = int(os.environ.get("SEED", "42"))
MIGRATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrate.sql")

summary = []


def log(msg=""):
    print(msg, flush=True)
    summary.append(msg)


def get_password():
    from google.cloud import secretmanager
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{DB_SECRET}/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode().strip()


def query(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def run_migration(conn):
    with open(MIGRATION_FILE) as f:
        statements = [s.strip() for s in f.read().split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)


def check_migration(conn):
    counts = query(conn, """
        SELECT (SELECT COUNT(*) FROM successful_requests) AS old_rows,
               (SELECT COUNT(*) FROM countries)           AS countries,
               (SELECT COUNT(*) FROM ip_addresses)        AS ips,
               (SELECT COUNT(*) FROM requests)            AS requests
    """).iloc[0]
    multi = query(conn, """
        SELECT COUNT(*) AS n FROM (
          SELECT client_ip FROM successful_requests
          GROUP BY client_ip HAVING COUNT(DISTINCT country) > 1
        ) t
    """).iloc[0]["n"]
    rebuilt = query(conn, """
        SELECT COUNT(*) AS n
        FROM successful_requests o
        JOIN requests r     ON r.id = o.id
        JOIN ip_addresses i ON i.client_ip = r.client_ip
        JOIN countries c    ON c.country_id = i.country_id
        WHERE c.country_name = o.country AND c.is_banned = o.is_banned
          AND r.gender = o.gender AND r.age = o.age AND r.income = o.income
          AND r.time_of_day = o.time_of_day AND r.requested_file = o.requested_file
    """).iloc[0]["n"]
    log("== Migration checks")
    log(f"Rows: old table {counts.old_rows}, countries {counts.countries}, "
        f"ip_addresses {counts.ips}, requests {counts.requests}")
    log(f"IPs seen with more than one country: {multi}")
    log(f"Old rows rebuilt exactly from the 3NF tables: {rebuilt} of {counts.old_rows}")


def load_data(conn):
    return query(conn, """
        SELECT r.id, r.client_ip, c.country_name AS country, r.gender, r.age,
               r.income, HOUR(r.time_of_day) AS hour
        FROM requests r
        JOIN ip_addresses i ON i.client_ip = r.client_ip
        JOIN countries c    ON c.country_id = i.country_id
        ORDER BY r.id
    """)


def ip_country_model(df):
    octets = df["client_ip"].str.split(".", expand=True).iloc[:, :3].astype(int)
    octets.columns = ["octet1", "octet2", "octet3"]
    X_train, X_test, y_train, y_test, ip_train, ip_test = train_test_split(
        octets, df["country"], df["client_ip"], test_size=0.2, random_state=SEED)

    model = DecisionTreeClassifier(random_state=SEED).fit(X_train, y_train)
    pred = model.predict(X_test)
    accuracy = (pred == y_test.to_numpy()).mean()

    log("== Model 1: client IP -> country")
    log("Decision tree on the first three octets of the IP")
    log(f"Train rows {len(X_train)}, test rows {len(X_test)}, leaves {model.get_n_leaves()}")
    log(f"Test accuracy: {accuracy:.4%}")

    return pd.DataFrame({
        "client_ip": ip_test.to_numpy(),
        "actual_country": y_test.to_numpy(),
        "predicted_country": pred,
        "correct": (pred == y_test.to_numpy()).astype(int),
    })


def income_pipeline(features):
    encode = ColumnTransformer([("onehot", OneHotEncoder(handle_unknown="ignore"), features)])
    return Pipeline([("encode", encode), ("tree", DecisionTreeClassifier(random_state=SEED))])


def income_model(df):
    data = df.assign(hour=df["hour"].astype(str))
    features = ["age", "gender"]
    train, test = train_test_split(data, test_size=0.2, random_state=SEED)

    baseline_guess = train["income"].mode()[0]
    baseline = (test["income"] == baseline_guess).mean()

    model = income_pipeline(features).fit(train[features], train["income"])
    pred = model.predict(test[features])
    accuracy = (pred == test["income"].to_numpy()).mean()

    log("== Model 2: age + gender -> income")
    log("Decision tree on one-hot encoded age group and gender")
    log(f"Train rows {len(train)}, test rows {len(test)}")
    log(f"Test accuracy: {accuracy:.4%}")
    log(f"Baseline (always guess '{baseline_guess}'): {baseline:.4%}")

    log("Predicted income for each age group:")
    for age in sorted(data["age"].unique(), key=lambda a: int(a.split("-")[0].rstrip("+"))):
        for gender in sorted(data["gender"].unique()):
            guess = model.predict(pd.DataFrame({"age": [age], "gender": [gender]}))[0]
            log(f"  {age:>6} {gender:<7} -> {guess}")

    log("Test accuracy with other feature sets (same split):")
    for extra in (["age"], ["age", "hour"], ["age", "country"], ["age", "gender", "hour", "country"]):
        m = income_pipeline(extra).fit(train[extra], train["income"])
        acc = (m.predict(test[extra]) == test["income"].to_numpy()).mean()
        log(f"  {' + '.join(extra):<30} {acc:.4%}")

    seed_scores = []
    for seed in (1, 2, 3, 4, 5):
        tr, te = train_test_split(data, test_size=0.2, random_state=seed)
        m = income_pipeline(features).fit(tr[features], tr["income"])
        seed_scores.append((m.predict(te[features]) == te["income"].to_numpy()).mean())
    log("Test accuracy of the same model on other random splits: "
        + ", ".join(f"{s:.2%}" for s in seed_scores))

    return pd.DataFrame({
        "age": test["age"].to_numpy(),
        "gender": test["gender"].to_numpy(),
        "actual_income": test["income"].to_numpy(),
        "predicted_income": pred,
        "correct": (pred == test["income"].to_numpy()).astype(int),
    })


def upload(bucket, name, text, content_type):
    path = f"{OUT_PREFIX}/{name}"
    bucket.blob(path).upload_from_string(text, content_type=content_type)
    print(f"Wrote gs://{BUCKET}/{path}", flush=True)


def main():
    from google.cloud import storage
    from google.cloud.sql.connector import Connector

    connector = Connector()
    conn = connector.connect(INSTANCE, "pymysql", user=DB_USER, password=get_password(),
                             db=DB_NAME, autocommit=True)
    try:
        run_migration(conn)
        check_migration(conn)
        df = load_data(conn)
    finally:
        conn.close()
        connector.close()

    log(f"Loaded {len(df)} requests through the 3NF tables")
    ip_results = ip_country_model(df)
    income_results = income_model(df)

    bucket = storage.Client(project=PROJECT_ID).bucket(BUCKET)
    upload(bucket, "ip_country_test_predictions.csv", ip_results.to_csv(index=False), "text/csv")
    upload(bucket, "income_test_predictions.csv", income_results.to_csv(index=False), "text/csv")
    upload(bucket, "summary.txt", "\n".join(summary) + "\n", "text/plain")


if __name__ == "__main__":
    main()
