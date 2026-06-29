import { computed, ref } from "vue";
import {
  getCurrentUser,
  login as loginApi,
  logout as logoutApi,
  register as registerApi,
  type AuthRequestPayload,
  type UserProfile,
} from "../api";

function messageFromError(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function useAuth() {
  const currentUser = ref<UserProfile | null>(null);
  const loading = ref(false);
  const errorMessage = ref("");

  const isAuthenticated = computed(() => Boolean(currentUser.value?.authenticated));
  const isGuest = computed(() => Boolean(currentUser.value?.is_guest ?? true));

  function clearError() {
    errorMessage.value = "";
  }

  async function loadCurrentUser() {
    try {
      currentUser.value = await getCurrentUser();
      clearError();
      return currentUser.value;
    } catch (error) {
      currentUser.value = null;
      errorMessage.value = messageFromError(error, "获取当前用户失败");
      throw error;
    }
  }

  async function login(payload: AuthRequestPayload) {
    loading.value = true;
    clearError();
    try {
      const result = await loginApi(payload);
      currentUser.value = result.user;
      return result;
    } catch (error) {
      errorMessage.value = messageFromError(error, "登录失败");
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function register(payload: AuthRequestPayload) {
    loading.value = true;
    clearError();
    try {
      const result = await registerApi(payload);
      currentUser.value = result.user;
      return result;
    } catch (error) {
      errorMessage.value = messageFromError(error, "注册失败");
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function logout() {
    loading.value = true;
    clearError();
    try {
      await logoutApi();
      currentUser.value = await getCurrentUser().catch(() => null);
    } catch (error) {
      errorMessage.value = messageFromError(error, "退出失败");
      throw error;
    } finally {
      loading.value = false;
    }
  }

  return {
    currentUser,
    loading,
    errorMessage,
    isAuthenticated,
    isGuest,
    loadCurrentUser,
    login,
    register,
    logout,
    clearError,
  };
}
