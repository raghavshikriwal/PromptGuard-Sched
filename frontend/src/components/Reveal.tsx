import { useEffect, useRef, useState, type ReactNode } from "react";
import { cssVars } from "./ui";

interface RevealProps {
  readonly delay?: number;
  readonly className?: string;
  readonly children: ReactNode;
}

const THRESHOLD = 0.15;
const ROOT_MARGIN = "0px 0px -8% 0px";

/**
 * Fades and lifts its children into place once, the first time they scroll into view.
 * Content is visible immediately when IntersectionObserver is unavailable (tests, old
 * browsers); reduced-motion users are handled in motion.css.
 */
export default function Reveal({ delay = 0, className = "", children }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(typeof IntersectionObserver === "undefined");

  useEffect(() => {
    const node = ref.current;
    if (visible || !node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: THRESHOLD, rootMargin: ROOT_MARGIN },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible]);

  return (
    <div
      ref={ref}
      data-visible={visible}
      className={`reveal ${className}`}
      style={cssVars({ "--reveal-delay": `${delay}ms` })}
    >
      {children}
    </div>
  );
}
