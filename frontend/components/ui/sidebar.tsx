"use client";

import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { motion } from "framer-motion";
import {
  ChevronsUpDown,
  CircleCheck,
  FileText,
  Home,
  LogOut,
  Settings,
  TriangleAlert,
  Upload,
  UserCircle,
  type LucideIcon,
} from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LanguageToggle } from "@/components/ui/language-toggle";
import { useT } from "@/app/lib/i18n";

const sidebarVariants = {
  open: {
    width: "15rem",
  },
  closed: {
    width: "3.05rem",
  },
};

const contentVariants = {
  open: { display: "block", opacity: 1 },
  closed: { display: "block", opacity: 1 },
};

const variants = {
  open: {
    x: 0,
    opacity: 1,
    transition: {
      x: { stiffness: 1000, velocity: -100 },
    },
  },
  closed: {
    x: -20,
    opacity: 0,
    transition: {
      x: { stiffness: 100 },
    },
  },
};

const transitionProps = {
  type: "tween",
  ease: "easeOut",
  duration: 0.2,
  staggerChildren: 0.1,
} as const;

const staggerVariants = {
  open: {
    transition: { staggerChildren: 0.03, delayChildren: 0.02 },
  },
};

interface NavItem {
  labelKey: string;
  url: string;
  icon: LucideIcon;
  /** Visible but disabled — part of the eventual workflow, not ready yet. */
  comingSoon?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { labelKey: "nav.dashboard", url: "/", icon: Home },
  { labelKey: "nav.ingestion", url: "/ingestion", icon: Upload },
  { labelKey: "nav.reconciliation", url: "/reconciliation", icon: CircleCheck },
  { labelKey: "nav.mismatches", url: "/mismatches", icon: TriangleAlert },
  { labelKey: "nav.invoices", url: "/invoices", icon: FileText, comingSoon: true },
  { labelKey: "nav.settings", url: "/settings", icon: Settings },
];

export function SessionNavBar() {
  const [isCollapsed, setIsCollapsed] = useState(true);
  const pathname = usePathname();
  const t = useT();

  const isItemActive = (url: string) =>
    url === "/" ? pathname === "/" : pathname.startsWith(url);

  return (
    <motion.div
      className={cn(
        "sidebar fixed left-0 z-40 h-full shrink-0 border-r border-border",
      )}
      initial={isCollapsed ? "closed" : "open"}
      animate={isCollapsed ? "closed" : "open"}
      variants={sidebarVariants}
      transition={transitionProps}
      onMouseEnter={() => setIsCollapsed(false)}
      onMouseLeave={() => setIsCollapsed(true)}
    >
      <motion.div
        className="relative z-40 flex h-full shrink-0 flex-col bg-card text-foreground transition-all"
        variants={contentVariants}
      >
        <motion.ul variants={staggerVariants} className="flex h-full flex-col">
          <div className="flex grow flex-col items-center">
            {/* Brand wordmark — collapses to "C", expands to "Credarion" */}
            <div className="flex h-[54px] w-full shrink-0 items-center border-b border-border px-3">
              <Link href="/" className="flex w-full items-center gap-2">
                <span className="text-lg font-bold text-accent">C</span>
                <motion.li variants={variants} className="list-none">
                  {!isCollapsed && (
                    <span className="text-[15px] font-semibold tracking-tight text-foreground">
                      Credarion
                    </span>
                  )}
                </motion.li>
              </Link>
            </div>

            <div className="flex h-full w-full flex-col">
              <div className="flex grow flex-col gap-4">
                <ScrollArea className="h-16 grow p-2">
                  <div className={cn("flex w-full flex-col gap-1")}>
                    {NAV_ITEMS.map((item) => {
                      const Icon = item.icon;
                      const active = isItemActive(item.url);

                      // "Coming Soon" items stay visible but are not navigable.
                      if (item.comingSoon) {
                        return (
                          <div
                            key={item.url}
                            aria-disabled="true"
                            title={t("nav.invoices_soon")}
                            className="flex h-8 w-full cursor-not-allowed flex-row items-center rounded-md px-2 py-1.5 text-muted-foreground/50"
                          >
                            <Icon className="h-4 w-4 shrink-0" />
                            <motion.li variants={variants} className="list-none">
                              {!isCollapsed && (
                                <span className="ml-2 flex items-center gap-1.5">
                                  <span className="text-sm font-medium">
                                    {t(item.labelKey)}
                                  </span>
                                  <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                    {t("nav.invoices_soon")}
                                  </span>
                                </span>
                              )}
                            </motion.li>
                          </div>
                        );
                      }

                      return (
                        <Link
                          key={item.url}
                          href={item.url}
                          className={cn(
                            "flex h-8 w-full flex-row items-center rounded-md px-2 py-1.5 text-muted-foreground transition hover:bg-muted hover:text-accent",
                            active && "bg-accent-light text-accent",
                          )}
                        >
                          <Icon className="h-4 w-4 shrink-0" />
                          <motion.li variants={variants} className="list-none">
                            {!isCollapsed && (
                              <p className="ml-2 text-sm font-medium">
                                {t(item.labelKey)}
                              </p>
                            )}
                          </motion.li>
                        </Link>
                      );
                    })}
                  </div>
                </ScrollArea>
              </div>

              <div className="flex flex-col gap-1 p-2">
                {/* Language toggle — only meaningful when the rail is expanded */}
                <motion.li variants={variants} className="list-none">
                  {!isCollapsed && (
                    <div className="px-1 pb-1">
                      <LanguageToggle />
                    </div>
                  )}
                </motion.li>

                {/* Account */}
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger className="w-full">
                    <div className="flex h-8 w-full flex-row items-center gap-2 rounded-md px-2 py-1.5 text-muted-foreground transition hover:bg-muted hover:text-accent">
                      <Avatar className="size-4">
                        <AvatarFallback className="text-[10px]">A</AvatarFallback>
                      </Avatar>
                      <motion.li
                        variants={variants}
                        className="flex w-full list-none items-center gap-2"
                      >
                        {!isCollapsed && (
                          <>
                            <p className="text-sm font-medium">
                              {t("nav.account")}
                            </p>
                            <ChevronsUpDown className="ml-auto h-4 w-4 text-muted-foreground/50" />
                          </>
                        )}
                      </motion.li>
                    </div>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent sideOffset={5}>
                    <div className="flex flex-row items-center gap-2 p-2">
                      <Avatar className="size-6">
                        <AvatarFallback className="text-xs">A</AvatarFallback>
                      </Avatar>
                      <div className="flex flex-col text-left">
                        <span className="text-sm font-medium">Account</span>
                        <span className="line-clamp-1 text-xs text-muted-foreground">
                          {t("nav.account_hint")}
                        </span>
                      </div>
                    </div>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild className="flex items-center gap-2">
                      <Link href="/settings">
                        <UserCircle className="h-4 w-4" /> {t("nav.profile")}
                      </Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem className="flex items-center gap-2">
                      <LogOut className="h-4 w-4" /> {t("nav.sign_out")}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          </div>
        </motion.ul>
      </motion.div>
    </motion.div>
  );
}
