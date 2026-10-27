// A development-only preview. A VITE flag alone can never open a production build.
export const jdLabEnabled = () => import.meta.env.DEV && import.meta.env.VITE_PATHWISE_JD_LAB === 'synthetic-v1'
