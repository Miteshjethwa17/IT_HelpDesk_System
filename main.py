from database import db
from dashboard import dashboard_service
from reports import report_service
from auth import auth
from ticket import ticket_service


def main():
    try:
        db.connect()
        print("\nDatabase Connected Successfully")
        print("\nLOGIN TEST")
        email = input("Email: ")
        password = input("Password: ")

        user = auth.login(email, password)

        print(f"\nWelcome {user.full_name}")
        print(f"Role: {user.role}")  

        while True:
            print("\n" + "=" * 50)
            print("      IT HELP DESK SYSTEM")
            print("=" * 50)
            print("1. View Dashboard")
            print("2. View Reports")
            print("3. Exit")

            choice = input("\nEnter choice: ")

            if choice == "1":
                dashboard_service.print_dashboard()

            elif choice == "2":
                report_service.ticket_status_report()
                report_service.assignment_report()

            elif choice == "3":
                print("Exiting Application...")
                break

            else:
                print("Invalid choice!")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        db.disconnect()

if __name__ == "__main__":
    main()