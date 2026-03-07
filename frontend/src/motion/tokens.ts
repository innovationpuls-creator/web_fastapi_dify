import type { Transition } from "framer-motion";

export type MotionSource = "user" | "system" | "stream";

export const MOTION_EASE = {
  standard: [0.22, 1, 0.36, 1] as const,
  emphasized: [0.16, 1, 0.3, 1] as const,
  accelerate: [0.3, 0, 0.8, 0.15] as const,
};

export const MOTION_DURATION = {
  micro: 0.16,
  short: 0.24,
  medium: 0.32,
  long: 0.42,
};

export const MOTION_SPRING = {
  panel: {
    type: "spring",
    stiffness: 360,
    damping: 32,
    mass: 0.9,
  } satisfies Transition,
  sheet: {
    type: "spring",
    stiffness: 420,
    damping: 34,
    mass: 0.88,
  } satisfies Transition,
  list: {
    type: "spring",
    stiffness: 380,
    damping: 30,
    mass: 0.82,
  } satisfies Transition,
  bubble: {
    type: "spring",
    stiffness: 420,
    damping: 28,
    mass: 0.78,
  } satisfies Transition,
};

export const MOTION_TRANSITION = {
  fade: {
    duration: MOTION_DURATION.short,
    ease: MOTION_EASE.standard,
  } satisfies Transition,
  enter: {
    duration: MOTION_DURATION.medium,
    ease: MOTION_EASE.emphasized,
  } satisfies Transition,
  soft: {
    duration: MOTION_DURATION.micro,
    ease: MOTION_EASE.standard,
  } satisfies Transition,
  layout: {
    duration: MOTION_DURATION.medium,
    ease: MOTION_EASE.emphasized,
  } satisfies Transition,
};

export const isUserDrivenMotion = (source: MotionSource) => source === "user";

export const isAmbientMotion = (source: MotionSource) => source !== "user";

export const shouldAnimateLayout = (source: MotionSource) => source === "user";

export const getSceneTransition = (
  source: MotionSource,
  reduceMotion: boolean,
): Transition => {
  if (reduceMotion) {
    return MOTION_TRANSITION.fade;
  }

  return source === "user" ? MOTION_TRANSITION.enter : MOTION_TRANSITION.soft;
};
