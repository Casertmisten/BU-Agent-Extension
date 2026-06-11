import { type DBSchema, type IDBPDatabase, openDB } from 'idb'
import type { Session } from '@/types'

const DB_NAME = 'bu-agent-ext'
const DB_VERSION = 1

interface BuAgentDB extends DBSchema {
  sessions: {
    key: string
    value: Session
    indexes: { 'by-created': number }
  }
}

let dbPromise: Promise<IDBPDatabase<BuAgentDB>> | null = null

function getDB() {
  if (!dbPromise) {
    dbPromise = openDB<BuAgentDB>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        const store = db.createObjectStore('sessions', { keyPath: 'id' })
        store.createIndex('by-created', 'createdAt')
      },
    })
  }
  return dbPromise
}

/** 保存会话（自动生成 id 和 createdAt） */
export async function saveSession(
  session: Omit<Session, 'id' | 'createdAt'>,
): Promise<Session> {
  const db = await getDB()
  const record: Session = {
    ...session,
    id: crypto.randomUUID(),
    createdAt: Date.now(),
  }
  await db.put('sessions', record)
  return record
}

/** 列出所有会话（最新在前） */
export async function listSessions(): Promise<Session[]> {
  const db = await getDB()
  const all = await db.getAllFromIndex('sessions', 'by-created')
  return all.reverse()
}

/** 获取单个会话 */
export async function getSession(id: string): Promise<Session | undefined> {
  const db = await getDB()
  return db.get('sessions', id)
}

/** 删除会话 */
export async function deleteSession(id: string): Promise<void> {
  const db = await getDB()
  await db.delete('sessions', id)
}

/** 清空所有会话 */
export async function clearSessions(): Promise<void> {
  const db = await getDB()
  await db.clear('sessions')
}
