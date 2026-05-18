#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/docker-entrypoint-initdb.d/unitares"
PSQL=(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")

run_sql() {
    local rel_path="$1"
    echo "UNITARES init: applying ${rel_path}"
    "${PSQL[@]}" -f "${ROOT}/${rel_path}"
}

run_migration() {
    local path="$1"
    echo "UNITARES init: applying migrations/$(basename "$path")"
    "${PSQL[@]}" -f "$path"
}

run_sql "schema.sql"
run_sql "knowledge_schema.sql"
"${PSQL[@]}" -c "INSERT INTO core.schema_migrations (version, name, applied_at) VALUES (2, 'knowledge_schema', NOW()) ON CONFLICT (version) DO NOTHING;"

run_sql "embeddings_schema.sql"
run_sql "embeddings_bge_m3_schema.sql"

for migration in "${ROOT}"/migrations/*.sql; do
    base="$(basename "$migration")"
    version="${base%%_*}"
    case "$version" in
        ""|*[!0-9]*) continue ;;
    esac

    # 001 and 002 are markers for schema.sql and knowledge_schema.sql.
    # 031 extends partition maintenance, so partitions.sql must run first.
    if (( 10#$version >= 3 && 10#$version <= 30 )); then
        run_migration "$migration"
    fi
done

run_sql "partitions.sql"
run_sql "graph_schema.sql"

for migration in "${ROOT}"/migrations/*.sql; do
    base="$(basename "$migration")"
    version="${base%%_*}"
    case "$version" in
        ""|*[!0-9]*) continue ;;
    esac

    if (( 10#$version >= 31 )); then
        run_migration "$migration"
    fi
done

echo "UNITARES init: complete"
