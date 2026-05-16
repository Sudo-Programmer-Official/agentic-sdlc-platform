import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import {
  browserLocalPersistence,
  createUserWithEmailAndPassword,
  getAuth,
  onIdTokenChanged,
  setPersistence,
  signInWithEmailAndPassword,
  signOut,
} from "firebase/auth";

import { bootstrapFirstLogin, setActiveTenantId, setActiveWorkspaceId, setActiveWorkspaceMeta, setAuthToken } from "../api/lifecycle";

type FirebaseConfig = {
  apiKey: string;
  authDomain: string;
  projectId: string;
  appId: string;
};

function readFirebaseConfig(): FirebaseConfig | null {
  const apiKey = import.meta.env.VITE_FIREBASE_API_KEY as string | undefined;
  const authDomain = import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined;
  const projectId = import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined;
  const appId = import.meta.env.VITE_FIREBASE_APP_ID as string | undefined;
  if (!apiKey || !authDomain || !projectId || !appId) return null;
  return { apiKey, authDomain, projectId, appId };
}

function tenantFromClaims(claims: Record<string, any>): string | null {
  const candidates = [
    claims?.tenant_id,
    claims?.tenantId,
    claims?.["https://agentic-sdlc/tenant_id"],
    claims?.["https://foundercontent-ai/tenant_id"],
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function ensureFirebaseApp(config: FirebaseConfig): FirebaseApp {
  return getApps()[0] || initializeApp(config);
}

let persistenceConfigured = false;

async function ensureAuthPersistence() {
  if (persistenceConfigured) return;
  const config = readFirebaseConfig();
  if (!config) return;
  const app = ensureFirebaseApp(config);
  const auth = getAuth(app);
  await setPersistence(auth, browserLocalPersistence);
  persistenceConfigured = true;
}

export function bootstrapFirebaseSessionSync() {
  if (typeof window === "undefined") return;
  const config = readFirebaseConfig();
  if (!config) return;
  const app = ensureFirebaseApp(config);
  const auth = getAuth(app);
  void ensureAuthPersistence();
  onIdTokenChanged(auth, async (user) => {
    if (!user) {
      setAuthToken(null);
      setActiveTenantId(null);
      setActiveWorkspaceId(null);
      setActiveWorkspaceMeta(null);
      return;
    }
    const token = await user.getIdToken();
    setAuthToken(token);
    const claims = (await user.getIdTokenResult()).claims || {};
    const tenantId = tenantFromClaims(claims as Record<string, any>);
    if (tenantId) setActiveTenantId(tenantId);
  });
}

export async function loginWithEmailPassword(email: string, password: string) {
  const config = readFirebaseConfig();
  if (!config) {
    throw new Error("Firebase auth is not configured.");
  }
  await ensureAuthPersistence();
  const app = ensureFirebaseApp(config);
  const auth = getAuth(app);
  const credential = await signInWithEmailAndPassword(auth, email, password);
  const token = await credential.user.getIdToken();
  const bootstrap = await bootstrapFirstLogin(token);
  setActiveTenantId(bootstrap.tenant_id);
  setActiveWorkspaceId(bootstrap.workspace_id);
  setActiveWorkspaceMeta({ id: bootstrap.workspace_id, name: bootstrap.workspace_name || "Workspace" });
}

export async function signupWithEmailPassword(email: string, password: string) {
  const config = readFirebaseConfig();
  if (!config) {
    throw new Error("Firebase auth is not configured.");
  }
  await ensureAuthPersistence();
  const app = ensureFirebaseApp(config);
  const auth = getAuth(app);
  const credential = await createUserWithEmailAndPassword(auth, email, password);
  const token = await credential.user.getIdToken();
  const bootstrap = await bootstrapFirstLogin(token, { force_new_tenant: true });
  setActiveTenantId(bootstrap.tenant_id);
  setActiveWorkspaceId(bootstrap.workspace_id);
  setActiveWorkspaceMeta({ id: bootstrap.workspace_id, name: bootstrap.workspace_name || "Workspace" });
}

export async function logoutFirebaseSession() {
  const config = readFirebaseConfig();
  if (!config) {
    setAuthToken(null);
    setActiveTenantId(null);
    setActiveWorkspaceId(null);
    setActiveWorkspaceMeta(null);
    return;
  }
  const app = ensureFirebaseApp(config);
  const auth = getAuth(app);
  await signOut(auth);
  setAuthToken(null);
  setActiveTenantId(null);
  setActiveWorkspaceId(null);
  setActiveWorkspaceMeta(null);
}
