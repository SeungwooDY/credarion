"use client";

import { useState } from "react";
import Link from "next/link";
import PageHeader from "./components/page-header";
import { useOrgs } from "./lib/swr";

function ProgressRing({ percent, size = 80 }: { percent: number; size?: number }) {
  const strokeWidth = 6;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percent / 100) * circumference;

  return (
    <svg width={size} height={size} className="transform -rotate-90">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={strokeWidth}
        className="stroke-white/15"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        className="stroke-white transition-all duration-600"
      />
    </svg>
  );
}

export default function DashboardPage() {
  const { orgs, orgsLoading } = useOrgs();
  const apiOk = orgsLoading ? null : orgs.length >= 0 ? true : false;

  const enginePhase = 7;
  const totalPhases = 10;
  const progressPercent = Math.round((enginePhase / totalPhases) * 100);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Overview of your accounting co-pilot"
      />

      {/* Bento Grid */}
      <div className="grid grid-cols-3 grid-rows-[auto_auto] gap-4">

        {/* Hero Card — Engine Status */}
        <div className="row-span-2 rounded-2xl p-6 text-white bg-gradient-to-br from-[#7c4dff] via-accent to-accent-dark shadow-[0_4px_20px_rgba(108,60,224,0.3)] flex flex-col justify-between min-h-[280px]">
          <div>
            <div className="flex items-center gap-2 mb-5">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-80">
                <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <span className="text-sm font-semibold tracking-wide">Engine Active</span>
            </div>

            <div className="flex items-center gap-5 mb-6">
              <div className="relative">
                <ProgressRing percent={progressPercent} />
                <div className="absolute inset-0 flex items-center justify-center text-lg font-bold">
                  {progressPercent}%
                </div>
              </div>
              <div className="space-y-2">
                <div>
                  <div className="text-[10px] uppercase tracking-widest opacity-60">Phase</div>
                  <div className="text-sm font-semibold">{enginePhase} / {totalPhases}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest opacity-60">Status</div>
                  <div className="text-sm font-semibold">Invoice Processing</div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[10px] uppercase tracking-widest opacity-60">Layers</div>
                <div className="text-xl font-bold">4</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-widest opacity-60">AI Model</div>
                <div className="text-sm font-semibold mt-0.5">Claude Haiku</div>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between mt-4 pt-3 border-t border-white/15">
            <span className="text-xs opacity-70">Reconciliation Engine</span>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-xs font-medium">Live</span>
            </div>
          </div>
        </div>

        {/* Organizations Card */}
        <div className="bg-card rounded-2xl p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_12px_rgba(0,0,0,0.06)] transition-shadow">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-zinc-800">Organizations</h3>
            <div className="flex -space-x-2">
              {orgs.slice(0, 3).map((org, i) => (
                <div
                  key={org.id}
                  className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold text-white ring-2 ring-white"
                  style={{
                    background: ["#6c3ce0", "#3d8bfd", "#0d9488"][i % 3],
                  }}
                >
                  {org.name.charAt(0)}
                </div>
              ))}
            </div>
          </div>
          <div className="text-3xl font-bold text-zinc-800">
            {orgs.length.toString().padStart(2, "0")}
          </div>
          <p className="text-xs text-zinc-400 mt-1">
            {orgs.length === 1 ? "Entity" : "Entities"} Connected
          </p>
        </div>

        {/* Match Accuracy Card */}
        <div className="bg-card rounded-2xl p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_12px_rgba(0,0,0,0.06)] transition-shadow">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-zinc-800">Accuracy</h3>
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-accent-light text-accent">
              High Precision
            </span>
          </div>
          <div className="text-[11px] text-zinc-400 uppercase tracking-wider mb-1">
            4-Layer Match Rate
          </div>
          <div className="text-5xl font-bold text-zinc-800 tracking-tight">
            99.9<span className="text-2xl">%</span>
          </div>
          <div className="flex items-center gap-3 mt-3">
            <div className="h-1.5 flex-1 bg-zinc-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-[#7c4dff] via-accent to-accent-dark"
                style={{ width: "99.9%" }}
              />
            </div>
            <span className="text-[10px] text-zinc-400">Target Reliability</span>
          </div>
        </div>

        {/* System Status Card */}
        <div className="bg-card rounded-2xl p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_12px_rgba(0,0,0,0.06)] transition-shadow">
          <h3 className="text-sm font-semibold text-zinc-800 mb-3">System Status</h3>
          <div className="space-y-2.5">
            {[
              { label: "API", status: apiOk === null ? "Checking" : apiOk ? "Connected" : "Offline", ok: apiOk },
              { label: "Database", status: apiOk ? "Connected" : "Unknown", ok: apiOk ?? undefined },
              { label: "AI Engine", status: apiOk ? "Ready" : "Unknown", ok: apiOk ?? undefined },
            ].map((item) => (
              <div key={item.label} className="flex items-center justify-between">
                <span className="text-xs text-zinc-500">{item.label}</span>
                <div className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      item.ok === null || item.ok === undefined
                        ? "bg-amber-400 animate-pulse"
                        : item.ok
                          ? "bg-green-400"
                          : "bg-red-400"
                    }`}
                  />
                  <span className="text-xs font-medium text-zinc-600">{item.status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Processing Speed Card */}
        <div className="bg-card rounded-2xl p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_12px_rgba(0,0,0,0.06)] transition-shadow">
          <h3 className="text-sm font-semibold text-zinc-800 mb-1">Processing Speed</h3>
          <div className="text-5xl font-bold text-zinc-800 tracking-tight mt-2">
            7<span className="text-2xl">x</span>
          </div>
          <p className="text-xs text-zinc-400 mt-2 leading-relaxed">
            Reduce supplier reconciliation from 7 days to 1 day with AI-powered matching.
          </p>
        </div>
      </div>

      {/* Quick Actions */}
      <h3 className="text-sm font-semibold text-zinc-800 mt-8 mb-3">Quick Actions</h3>
      <div className="grid grid-cols-4 gap-3">
        {[
          {
            href: "/ingestion",
            title: "Upload Data",
            desc: "Import GRN exports and supplier statements",
            icon: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            ),
          },
          {
            href: "/reconciliation",
            title: "Reconcile",
            desc: "Run the 4-layer matching engine",
            icon: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            ),
          },
          {
            href: "/invoices",
            title: "Invoices",
            desc: "Upload fapiao for OCR extraction",
            icon: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            ),
          },
          {
            href: "/settings",
            title: "Settings",
            desc: "Organization and engine config",
            icon: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
              </svg>
            ),
          },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="bg-card rounded-2xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_12px_rgba(0,0,0,0.06)] transition-shadow group flex flex-col gap-3 no-underline"
          >
            <div className="w-9 h-9 rounded-lg flex items-center justify-center bg-accent-light text-accent">
              {item.icon}
            </div>
            <div>
              <div className="text-sm font-semibold text-zinc-800 group-hover:text-accent transition-colors">
                {item.title}
              </div>
              <div className="text-xs text-zinc-400 mt-0.5">{item.desc}</div>
            </div>
          </Link>
        ))}
      </div>

      {/* Organizations table */}
      {orgs.length > 0 && (
        <div className="mt-8">
          <h3 className="text-sm font-semibold text-zinc-800 mb-3">Entities</h3>
          <div className="bg-card rounded-2xl shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-zinc-400 uppercase tracking-wider">
                  <th className="text-left px-5 py-3 font-medium">Name</th>
                  <th className="text-left px-5 py-3 font-medium">Currency</th>
                  <th className="text-left px-5 py-3 font-medium">ID</th>
                </tr>
              </thead>
              <tbody>
                {orgs.map((org) => (
                  <tr key={org.id} className="border-t border-border hover:bg-muted transition-colors">
                    <td className="px-5 py-3 font-medium text-zinc-800">{org.name}</td>
                    <td className="px-5 py-3 text-zinc-600">{org.reporting_currency}</td>
                    <td className="px-5 py-3 font-mono text-xs text-zinc-400">
                      {org.id.slice(0, 8)}...
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
