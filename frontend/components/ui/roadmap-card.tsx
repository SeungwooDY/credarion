"use client";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export interface RoadmapItem {
  /** Short label shown in the badge (e.g. a step number or quarter). */
  quarter: string;
  title: string;
  description: string;
  status?: "done" | "in-progress" | "upcoming";
}

export interface RoadmapCardProps {
  title?: string;
  description?: string;
  items: RoadmapItem[];
  className?: string;
}

export function RoadmapCard({
  title = "Product Roadmap",
  description = "Upcoming features and releases",
  items,
  className,
}: RoadmapCardProps) {
  return (
    <Card
      className={cn(
        "w-full border-border shadow-none",
        className,
      )}
    >
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="relative">
          {/* Timeline Line */}
          <div className="absolute left-0 right-0 top-4 h-px bg-border" />

          <div className="flex justify-between">
            {items.map((item, index) => {
              const active =
                item.status === "done" || item.status === "in-progress";
              return (
                <motion.div
                  key={index}
                  className="relative w-1/4 pt-8 text-center"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: index * 0.15 }}
                >
                  {/* Timeline Dot */}
                  <motion.div
                    whileHover={{ scale: 1.2 }}
                    className={cn(
                      "absolute left-1/2 top-2 flex h-4 w-4 -translate-x-1/2 items-center justify-center rounded-full",
                      active ? "bg-primary" : "border-2 border-border bg-card",
                    )}
                  >
                    {active && (
                      <div className="h-1.5 w-1.5 rounded-full bg-background" />
                    )}
                  </motion.div>

                  {/* Step badge */}
                  <Badge
                    variant={active ? "default" : "outline"}
                    className="mb-1 text-[11px]"
                  >
                    {item.quarter}
                  </Badge>

                  {/* Title + Description */}
                  <h4 className="text-sm font-medium">{item.title}</h4>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {item.description}
                  </p>
                </motion.div>
              );
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
