import { create } from "zustand";

import type { Patient, UserInfo } from "../types";

const DEFAULT_DEPARTMENT_ID = "dep-card-01";

type AppState = {
  token: string | null;
  user: UserInfo | null;
  selectedDepartmentId: string;
  selectedPatient: Patient | null;
  setAuth: (token: string, user: UserInfo, selectedDepartmentId?: string) => void;
  logout: () => void;
  setDepartment: (departmentId: string) => void;
  setSelectedPatient: (patient: Patient | null) => void;
};

export const useAppStore = create<AppState>((set) => ({
  token: null,
  user: null,
  selectedDepartmentId: DEFAULT_DEPARTMENT_ID,
  selectedPatient: null,
  setAuth: (token, user, selectedDepartmentId) =>
    set({
      token,
      user,
      selectedDepartmentId: String(selectedDepartmentId || "").trim() || DEFAULT_DEPARTMENT_ID,
      selectedPatient: null,
    }),
  logout: () =>
    set({
      token: null,
      user: null,
      selectedDepartmentId: DEFAULT_DEPARTMENT_ID,
      selectedPatient: null,
    }),
  setDepartment: (selectedDepartmentId) => set({ selectedDepartmentId }),
  setSelectedPatient: (selectedPatient) => set({ selectedPatient })
}));
