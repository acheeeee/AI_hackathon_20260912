"""A1 資料庫地基：連線設定、migration、稽核 hash chain。"""

from pathlib import Path

from caseapi.audit import append_entry, read_entries
from caseapi.db.connection import connect, transaction
from caseapi.db.migrations import apply_migrations


def test_connection_enables_foreign_key_enforcement(tmp_path: Path) -> None:
    # Arrange
    conn = connect(tmp_path / 'a.db')

    # Act
    enabled = conn.execute('PRAGMA foreign_keys').fetchone()[0]

    # Assert
    assert enabled == 1


def test_applying_migrations_twice_records_each_version_once(tmp_path: Path) -> None:
    # Arrange
    conn = connect(tmp_path / 'a.db')

    # Act
    first_pass = apply_migrations(conn)
    second_pass = apply_migrations(conn)

    # Assert
    rows = conn.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall()
    versions = [row['version'] for row in rows]
    assert versions == sorted(set(versions))
    assert versions[0] == '001_initial'
    assert first_pass == versions
    assert second_pass == []


def test_cross_case_foreign_key_is_rejected(tmp_path: Path) -> None:
    # Arrange
    conn = connect(tmp_path / 'a.db')
    apply_migrations(conn)

    # Act / Assert: snapshot 指向不存在的案件應該失敗，而不是靜默寫入
    try:
        with transaction(conn):
            conn.execute(
                'INSERT INTO case_snapshots (case_id, revision, heads_json, parent_revision,'
                ' mutation_id, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                ('case_missing', 1, '{}', None, 'mut_x', 'actor_test', '2026-09-12T00:00:00Z'),
            )
    except Exception as exc:  # noqa: BLE001 - 這裡就是要確認 sqlite 有擋下來
        assert 'FOREIGN KEY' in str(exc).upper()
    else:
        raise AssertionError('cross-case insert should have been rejected')


def test_audit_entries_form_a_hash_chain(tmp_path: Path) -> None:
    # Arrange
    conn = connect(tmp_path / 'a.db')
    apply_migrations(conn)
    with transaction(conn):
        conn.execute(
            'INSERT INTO cases (id, owner_id, case_revision, workflow_state, active_heads_json,'
            ' title, official_case_no, created_at, updated_at)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('case_1', 'actor_test', 1, 'human_review', '{}', None, None, 'T', 'T'),
        )

    # Act
    with transaction(conn):
        append_entry(conn, case_id='case_1', actor_id='actor_test', action='case.created',
                     mutation_id='mut_1', reason=None)
        append_entry(conn, case_id='case_1', actor_id='actor_test', action='fact.updated',
                     mutation_id='mut_2', reason='人工更正送達日期')

    # Assert
    entries = read_entries(conn, case_id='case_1')
    assert [entry['sequence'] for entry in entries] == [1, 2]
    assert entries[0]['prev_hash'] is None
    assert entries[1]['prev_hash'] == entries[0]['entry_hash']
    assert entries[0]['entry_hash'] != entries[1]['entry_hash']
