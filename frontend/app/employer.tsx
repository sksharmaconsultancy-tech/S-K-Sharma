import InstallEntry from "@/src/components/InstallEntry";

export default function EmployerEntry() {
  return (
    <InstallEntry
      kind="employer"
      title="Employer Portal"
      subtitle="Sign in as Super Admin, Company Admin or Sub Admin to manage attendance, payroll and compliance."
      loginPath="/admin-pin-login"
      manifestHref="/manifest-employer.json"
      accentIcon="shield-checkmark"
    />
  );
}
