"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";

interface Org {
  id: string;
  name: string;
  reporting_currency: string;
}

interface DataContextValue {
  orgs: Org[];
  orgsLoading: boolean;
  refreshOrgs: () => void;
}

const DataContext = createContext<DataContextValue>({
  orgs: [],
  orgsLoading: true,
  refreshOrgs: () => {},
});

export function useOrgs() {
  return useContext(DataContext);
}

export default function DataProvider({ children }: { children: ReactNode }) {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgsLoading, setOrgsLoading] = useState(true);

  const refreshOrgs = useCallback(() => {
    setOrgsLoading(true);
    fetch("/api/v1/orgs")
      .then((r) => r.json())
      .then((data) => {
        setOrgs(data);
        setOrgsLoading(false);
      })
      .catch(() => {
        setOrgs([]);
        setOrgsLoading(false);
      });
  }, []);

  useEffect(() => {
    refreshOrgs();
  }, [refreshOrgs]);

  return (
    <DataContext value={{ orgs, orgsLoading, refreshOrgs }}>
      {children}
    </DataContext>
  );
}
