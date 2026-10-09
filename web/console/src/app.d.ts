declare global {
	namespace App {
		interface Locals {
			editor: { name: string; accountId: string } | null;
			session: string | null;
		}
	}
}

export {};
