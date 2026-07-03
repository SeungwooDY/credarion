"use client";

import { useRouter } from "next/navigation";
import NotificationBell, { type BellNotification, type NotificationTone } from "./notification-bell";
import { useNotifications, type AppNotification } from "@/app/lib/swr";
import { useT } from "@/app/lib/i18n";

const TYPE_TONE: Record<string, NotificationTone> = {
  escalation_created: "urgent",
  escalation_acknowledged: "info",
  escalation_resolved: "info",
  period_signed_off: "info",
  period_reopened: "warning",
};

/** Wires the presentational bell to the notifications API + i18n. */
export default function NotificationBellContainer() {
  const t = useT();
  const router = useRouter();
  const { notifications, unreadCount, markRead, markAllRead } = useNotifications();

  function toBell(n: AppNotification): BellNotification {
    const p = n.payload ?? {};
    const tokens = {
      actor: p.actor_name ?? "—",
      period: n.period ?? p.period ?? "—",
      title: p.escalation_title ?? "",
      org: p.org_name ?? "",
    };
    const titleByType: Record<string, string> = {
      escalation_created: t("notif.escalation_created", tokens),
      escalation_acknowledged: t("notif.escalation_acknowledged", tokens),
      escalation_resolved: t("notif.escalation_resolved", tokens),
      period_signed_off: t("notif.period_signed_off", tokens),
      period_reopened: t("notif.period_reopened", tokens),
    };
    return {
      id: n.id,
      title: titleByType[n.type] ?? n.type,
      detail: p.escalation_title || p.note || undefined,
      tone: TYPE_TONE[n.type] ?? "info",
      unread: n.read_at === null,
      href: n.escalation_id ? "/escalations" : "/",
    };
  }

  async function handleItemClick(bell: BellNotification) {
    const original = notifications.find((n) => n.id === bell.id);
    if (original && original.read_at === null) {
      await markRead(original.id);
    }
    if (bell.href) router.push(bell.href);
  }

  return (
    <NotificationBell
      notifications={notifications.map(toBell)}
      unreadCount={unreadCount}
      title={t("notif.title")}
      emptyLabel={t("notif.empty")}
      markAllLabel={t("notif.mark_all_read")}
      onItemClick={handleItemClick}
      onMarkAllRead={markAllRead}
    />
  );
}
