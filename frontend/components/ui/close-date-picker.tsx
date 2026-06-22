"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import useMeasure from "react-use-measure";
import { CalendarDays } from "lucide-react";
import type { DateValue } from "react-aria-components";
import { Calendar } from "@/components/ui/calendar-rac";

interface CloseDatePickerProps {
  value: DateValue | null;
  onChange: (date: DateValue) => void;
  /** Accessible label for the collapsed trigger. */
  label?: string;
}

/**
 * Small icon trigger that morphs open into a calendar popover — adapted from the
 * "smooth-dropdown" component (framer-motion + lucide instead of motion/react +
 * hugeicons). Used to set the month-end close date from the dashboard card.
 */
export function CloseDatePicker({ value, onChange, label }: CloseDatePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [contentRef, bounds] = useMeasure();

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    if (isOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const openW = Math.max(40, Math.ceil(bounds.width));
  const openH = Math.max(40, Math.ceil(bounds.height));

  return (
    <div ref={containerRef} className="relative h-7 w-7">
      <motion.div
        layout
        initial={false}
        animate={{
          width: isOpen ? openW : 28,
          height: isOpen ? openH : 28,
          borderRadius: isOpen ? 14 : 8,
        }}
        transition={{ type: "spring", damping: 34, stiffness: 380, mass: 0.8 }}
        className="absolute right-0 top-0 z-50 origin-top-right cursor-pointer overflow-hidden border border-border bg-popover shadow-lg"
        onClick={() => !isOpen && setIsOpen(true)}
      >
        {/* Collapsed trigger icon */}
        <motion.div
          initial={false}
          animate={{ opacity: isOpen ? 0 : 1, scale: isOpen ? 0.8 : 1 }}
          transition={{ duration: 0.15 }}
          className="absolute inset-0 flex items-center justify-center"
          style={{ pointerEvents: isOpen ? "none" : "auto", willChange: "transform" }}
          aria-hidden={isOpen}
        >
          <CalendarDays className="h-4 w-4 text-muted-foreground" aria-label={label} />
        </motion.div>

        {/* Calendar — measured at natural size (w-max) so the panel expands to fit */}
        <div ref={contentRef} className="w-max p-2">
          <motion.div
            initial={false}
            animate={{ opacity: isOpen ? 1 : 0 }}
            transition={{ duration: 0.2, delay: isOpen ? 0.08 : 0 }}
            style={{ pointerEvents: isOpen ? "auto" : "none", willChange: "transform" }}
          >
            <Calendar
              aria-label={label}
              value={value}
              onChange={(date) => {
                if (date && !Array.isArray(date)) onChange(date as DateValue);
                setIsOpen(false);
              }}
            />
          </motion.div>
        </div>
      </motion.div>
    </div>
  );
}
